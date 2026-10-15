"""既存の三標本・Lightweight Evidenceを配札等重みで比較する。探索処理は持たない。"""
from collections import Counter, defaultdict
import numpy as np
from pydantic import BaseModel, Field, ConfigDict
from .calibration_coverage import forecast_coverage, normalized
from .stratification_analysis import period
from .stopping_analysis import select_validation_positions
from .noise_analysis import stats
from .runner import derived_seed

FROZEN_MODEL_HASH = 'd7c08b175193cf6aa1593493ec9a0d8eddc5fb42c94aef1a1ef1740ad53fe3b9'
PERIODS = ('early','middle','before_final_round','final_round')


class CampaignCriteria(BaseModel):
    model_config = ConfigDict(extra='forbid')
    minimum_deals: int = Field(default=20, ge=20, le=100)
    reward_margin: float = Field(default=.05, ge=0, le=.1, allow_inf_nan=False)
    sign_tolerance: float = Field(default=0, ge=0, le=.000001, allow_inf_nan=False)
    bootstrap_repeats: int = Field(default=2000, ge=1000, le=5000)
    bootstrap_seed: int = Field(default=41001, ge=0, le=999999)


def campaign_positions(records, schedule):
    chosen=[];used=set()
    for label in schedule:
        options=[r for r in records if r['deal_hash'] not in used and normalized(r['period'])==label]
        selected=select_validation_positions(options,1)
        if not selected:raise ValueError('事前指定した未選択配札・時点の局面が不足。追加探索や枠補完はしません')
        chosen.extend(selected);used.add(selected[0]['deal_hash'])
    return chosen


def campaign_forecast(c, estimate):
    """Phase40の凍結係数・各時点の式をそのまま使用し、事前スロット割当だけ変える。"""
    base=forecast_coverage(c,estimate);slots=[];warnings=[]
    for i,label in enumerate(c.campaign_periods):
        turns=[t for t in c.turns if normalized(period(t))==label]
        one=forecast_coverage(c.model_copy(update={'turns':turns,'deals':1,'max_positions':1}),estimate)
        slots.append({**one['slots'][0],'ordinal':i});warnings.extend(one['warnings'])
    m=c.calibration;writes=base['storage_writes_upper']
    base.update(slots=slots,predicted_seconds=sum(s['predicted_search_seconds'] for s in slots)+m.management_seconds*c.deals+m.storage.mean_per_write*writes,
        conservative_seconds=sum(s['conservative_search_seconds'] for s in slots)+m.conservative_management_seconds*c.deals+m.storage.max_per_write*writes*m.safety_factor,
        simulated_turns_upper=sum(x['turns_upper'] for s in slots for x in s['components']),warnings=sorted(set(warnings)),
        allocation='事前固定campaign_periods。係数・安全係数はPhase40凍結モデルのまま。')
    base['rating']='予算内の見込み' if base['conservative_seconds']<=c.timeout_seconds else '予算超過のおそれ'
    base['coverage_status']='情報不足' if c.storage_history_rows is None or c.expected_payload_bytes is None else '一部範囲外' if warnings else '適用範囲内'
    return base


def sign(value,tolerance):return 'positive' if value>tolerance else 'negative' if value<-tolerance else 'zero'


def interval(values,criteria,domain):
    if len(values)<2:return None
    rng=np.random.default_rng(derived_seed(criteria.bootstrap_seed,'campaign-bootstrap-v1:'+domain))
    x=np.asarray(values,dtype=float)
    means=x[rng.integers(0,len(x),size=(criteria.bootstrap_repeats,len(x)))].mean(axis=1)
    return [float(np.quantile(means,.025)),float(np.quantile(means,.975))]


def decision_records(positions,tolerance=0):
    out=[]
    for p in positions:
        a=p['adaptive']
        for r in a['rows']:
            fixed=next(x for x in a['rows'] if x['model']==r['model'] and x['method']=='Fixed' and x['repeat']==r['repeat'])
            e=r['evaluations'][0];d=r['direct_measurement'];div=r['selected_card']!=fixed['selected_card'];delta=e['minus_fixed']['mean']
            category=('divergent_'+sign(delta,tolerance)) if div else 'same_early_stop' if r['early_stop'] else 'same_full_budget'
            ranked=sorted(r['candidates'],key=lambda x:(-x['reward'],x['card']['rank'],x['card']['suit']))
            selected=next(x for x in r['candidates'] if x['card']==r['selected_card'])
            out.append({'deal_hash':p['deal_hash'],'deal_id':p['deal_id'],'position_hash':p['position_hash'],
                'period':normalized(p['period']),'score_class':p['stratum']['class'],'scores':p['game_scores'],'turn':p['turn'],
                'source':p['source'],'model':r['model'],'method':r['method'],'repeat':r['repeat'],'legal_count':a['legal_count'],
                'selected_card':r['selected_card'],'fixed_card':fixed['selected_card'],'worlds':r['cost']['hidden_worlds'],
                'fixed_worlds':fixed['cost']['hidden_worlds'],'selection_estimate_rank':next(i+1 for i,x in enumerate(ranked) if x['card']==r['selected_card']),
                'estimated_reward':selected['reward'],'estimated_immediate_middle':selected['immediate_middle'],
                'independent_reward':e['value'],'reward_difference':delta,'minus_self':e['minus_self']['mean'],
                'estimated_regret':e['estimated_regret']['mean'],'early_stop':r['early_stop'],'diverged':div,'category':category,
                'wall_seconds':d['wall_seconds'],'wall_difference':d['wall_seconds']-fixed['direct_measurement']['wall_seconds'],
                'games_difference':r['cost']['derived_games']-fixed['cost']['derived_games'],
                'turns_difference':r['cost']['simulated_turns']-fixed['cost']['simulated_turns'],
                'selected_estimates':r['candidates'],'fixed_estimates':fixed['candidates'],
                'independent_candidates':a['final'][r['model']]['candidates'],
                'stopping_checkpoint':r['trace'][-1] if r['trace'] else None,
                'fixed_checkpoint_at_stop':next(({k:t.get(k) for k in ('worlds','selected_card','estimated_reward','gap')} for t in fixed['trace'] if t['worlds']==r['cost']['hidden_worlds']),None),
                'fixed_final_checkpoint':{k:fixed['trace'][-1].get(k) for k in ('worlds','selected_card','estimated_reward','gap')} if fixed['trace'] else None,
                'selection_reversed_after_stop':div,
                'post_stop_fixed_changes':r.get('post_stop_fixed_changes'),
                'stage_seeds':a['stage_seeds'],
                'score_change':None,'score_change_note':'候補別の累積得点変化は既存Evidenceに未保存。即時中位率は仮想対局の推定であり実際の獲得結果ではない。'})
    return out


METRICS=('wall_seconds','wall_difference','reward_difference','minus_self','estimated_regret','worlds','games_difference','turns_difference','early_stop','diverged','independent_reward')


def grouped_deals(records):
    """反復→局面内モデル→局面→配札。各階層を等重みにする。"""
    buckets=defaultdict(lambda:defaultdict(lambda:defaultdict(list)))
    for r in records:buckets[r['deal_hash']][r['position_hash']][r['model']].append(r)
    return [{'deal_hash':dh,**{k:float(np.mean([np.mean([np.mean([r[k] for r in rs]) for rs in models.values()]) for models in ps.values()])) for k in METRICS}}
        for dh,ps in sorted(buckets.items())]


def summarize(records,criteria,label):
    ds=grouped_deals(records);n=len(ds)
    wall=interval([d['wall_difference'] for d in ds],criteria,label+':wall');reward=interval([d['reward_difference'] for d in ds],criteria,label+':reward')
    adoption='現時点では採用根拠不足'
    if n>=criteria.minimum_deals:
        adoption='条件付き採用候補' if wall and reward and wall[1]<0 and reward[0]>=-criteria.reward_margin else '継続検証'
    if label.startswith('Fixed'):adoption='比較基準'
    return {'independent_deals':n,'paired_deals':ds,'metrics':{k:stats([d[k] for d in ds]) for k in METRICS},
        'wall_interval':wall,'reward_interval':reward,'reward_signs':dict(Counter(sign(d['reward_difference'],criteria.sign_tolerance) for d in ds)),
        'divergent_decisions':sum(r['diverged'] for r in records),'decisions':len(records),
        'divergent_positions':len({r['position_hash'] for r in records if r['diverged']}),
        'divergent_deals':len({r['deal_hash'] for r in records if r['diverged']}),
        'divergent_reward_signs':dict(Counter(sign(r['reward_difference'],criteria.sign_tolerance) for r in records if r['diverged'])),
        'categories':dict(Counter(r['category'] for r in records)),'adoption':adoption,
        'bootstrap_seeds':{k:str(derived_seed(criteria.bootstrap_seed,'campaign-bootstrap-v1:'+label+':'+k)) for k in ('wall','reward')},
        'negative_reward_decisions':sum(r['reward_difference'] < -criteria.sign_tolerance for r in records)}


def campaign_summary(positions,criteria,*,complete):
    records=decision_records(positions,criteria.sign_tolerance);primary=[];secondary=[]
    if complete:
        for method in ('Fixed','Gap-Adaptive','Uncertainty-Adaptive'):
            rs=[r for r in records if r['method']==method]
            primary.append({'method':method,**summarize(rs,criteria,method)})
            for key in ('model','period','score_class'):
                for value in sorted({r[key] for r in rs}):
                    secondary.append({'method':method,'stratum':key,'value':value,**summarize([r for r in rs if r[key]==value],criteria,method+':'+key+':'+value)})
    positions_by_period=Counter(normalized(p['period']) for p in positions);classes=Counter(p['stratum']['class'] for p in positions)
    return {'version':'adaptive-campaign-v1','primary_finalized':complete,'primary':primary if complete else None,'secondary_exploratory':secondary if complete else None,
        'partial_evidence':records,'divergence_evidence':[r for r in records if r['diverged']],
        'evaluated_deals':len({p['deal_hash'] for p in positions}),'evaluated_positions':len(positions),
        'periods':dict(positions_by_period),'score_classes':dict(classes),'missing_periods':[p for p in PERIODS if not positions_by_period[p]],
        'missing_score_classes':[p for p in ('highest','strict_middle','lowest','tie') if not classes[p]],'criteria':criteria.model_dump(mode='json'),
        'uncertainty':'独立配札の対応差をpercentile bootstrap（95%、探索的）で再標本化。小標本と多重な層別比較は不安定。全差0の退化区間は同等性の証明ではない。',
        'unit':'反復→局面内モデル→局面→独立配札の等重み。判断数と分岐配札数を区別。未完了時は部分Evidenceのみ。'}
