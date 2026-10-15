"""保存済み探索軌跡の分析。選択・停止・Finalの入力には利用しない。"""
from collections import Counter,defaultdict
from itertools import combinations
import numpy as np
from .campaign_analysis import CampaignCriteria,PERIODS,interval
from .divergence_coverage import CLASSES,score_class
from .noise_analysis import stats
from .stopping_analysis import rate_interval
from .calibration_coverage import normalized
from .stratification_analysis import period
from .evolution import digest
from ..game.rules import RULE_VERSION
from ..game.rewards import REWARD_VERSION

QUALITY=('Complete Comparable','Partial Comparable','Descriptive Only','Incompatible','Unknown')


def checkpoint_features(t):
    if t is None:return None
    candidates=t.get('candidates')
    ranked=sorted(candidates,key=lambda x:(-x['reward'],x['card']['rank'],x['card']['suit'])) if candidates else []
    return {'worlds':t['worlds'],'top_gap':ranked[0]['reward']-ranked[1]['reward'] if len(ranked)>1 else None,
        'minimum_pair_gap':min((abs(a['reward']-b['reward']) for a,b in combinations(ranked,2)),default=None),
        'selected_card':t.get('selected_card'),'ranking':[x['card'] for x in ranked] if ranked else None,
        'candidates':candidates,'gap_from_saved_trace':t.get('gap')}


def boundary_records(jobs):
    out=[];inventory=[]
    for v in jobs:
        counts=Counter();cfg=v.get('config',{});snap=v.get('snapshot',{});phase=cfg.get('revision','phase35' if v.get('experiment_kind')=='stopping_runtime_v1' else 'unknown')
        for p in v.get('positions',[]):
            a=p.get('adaptive',{})
            for r in a.get('rows',[]):
                fixed=next((x for x in a['rows'] if (x.get('model'),x.get('repeat'),x.get('budget'),x.get('method'))==(r.get('model'),r.get('repeat'),r.get('budget'),'Fixed')),None)
                evaluation=next((e for e in r.get('evaluations',[]) if e.get('model')==r.get('model')),None)
                seeds=a.get('stage_seeds',{});independent=len(seeds)==3 and len({str(x) for x in seeds.values()})==3
                comparable=bool(fixed and evaluation and isinstance(evaluation.get('minus_fixed'),dict))
                compatible=r.get('budget')==128 and cfg.get('gap_threshold')==.5 and cfg.get('uncertainty_z')==2 and cfg.get('minimum_gap')==.05 and snap.get('rule')==RULE_VERSION and snap.get('reward')==REWARD_VERSION
                quality='Unknown' if fixed is None else 'Incompatible' if not compatible else 'Descriptive Only' if not comparable or not independent else 'Complete Comparable' if v['status']=='Completed' and r.get('direct_measurement',{}).get('measurement_completed') else 'Partial Comparable'
                counts[quality]+=1;trace=fixed.get('trace',[]) if fixed else []
                checkpoints={str(n):checkpoint_features(next((t for t in trace if t['worlds']==n),None)) for n in (16,32,64,128)}
                rankings=[checkpoint_features(t)['ranking'] for t in trace];leaders=[t.get('selected_card') for t in trace]
                div=r.get('selected_card')!=fixed.get('selected_card') if fixed else None
                direct=r.get('direct_measurement');fd=fixed.get('direct_measurement') if fixed else None
                delta=evaluation['minus_fixed'].get('mean') if comparable else None
                scores=p.get('game_scores',p.get('observation',{}).get('game_scores'));player=p.get('player',p.get('observation',{}).get('player'))
                family=digest({'phase':phase,'rules':snap.get('rule'),'reward':snap.get('reward'),'sampler':snap.get('sampler'),
                    'series':cfg.get('boundary_series',cfg.get('collection_series',cfg.get('series'))),'stage':cfg.get('stage'),'stop':{k:cfg.get(k) for k in ('initial_worlds','batch_worlds','gap_threshold','uncertainty_z','minimum_gap')},
                    'budget':r.get('budget'),'reference':cfg.get('reference_worlds'),'final':cfg.get('final_worlds')})
                out.append({'experiment_id':v['id'],'phase':phase,'plan_hash':snap.get('study_plan_hash',snap.get('runtime_plan_hash')),
                    'status':v['status'],'quality':quality,'comparison_family':family,'deal_hash':p['deal_hash'],'position_hash':p['position_hash'],
                    'model':r.get('model'),'repeat':r.get('repeat'),'method':r.get('method'),'budget':r.get('budget'),
                    'selected_card':r.get('selected_card'),'fixed_card':fixed.get('selected_card') if fixed else None,'worlds':r.get('cost',{}).get('hidden_worlds'),
                    'early_stop':r.get('early_stop'),'diverged':div,'group':'D' if div else 'ND' if div is False else 'Unknown',
                    'checkpoints':checkpoints,'rank_changes':sum(x!=y for x,y in zip(rankings,rankings[1:])) if trace and all(x is not None for x in rankings) else None,
                    'leader_changes':sum(x!=y for x,y in zip(leaders,leaders[1:])) if trace else None,
                    'rank_change_scope':'保存済み全チェックポイント間。欠測区間内の変化回数は不明。',
                    'selected_candidates':r.get('candidates'),'fixed_candidates':fixed.get('candidates') if fixed else None,
                    'independent_candidates':a.get('final',{}).get(r.get('model'),{}).get('candidates'),
                    'independent_reward':evaluation.get('value') if evaluation else None,'reward_difference':delta,
                    'wall_difference':direct['wall_seconds']-fd['wall_seconds'] if direct and fd and direct.get('measurement_completed') and fd.get('measurement_completed') else None,
                    'period':normalized(p['period']),'turn':p['turn'],'score_class':score_class(scores,player) if scores is not None and player is not None else None,
                    'scores':scores,'source':p.get('source'),'legal_count':a.get('legal_count'),'measurement_mode':direct.get('mode') if direct else 'not_measured',
                    'stage_seeds':{k:str(x) for k,x in seeds.items()},'independent_streams':independent,
                    'anomaly':bool(div and not r.get('early_stop')),'role':'measurement_only' if cfg.get('boundary_series')=='M' else 'crossed_exploratory' if cfg.get('boundary_series')=='C' else 'historical_exploratory'})
        inventory.append({'experiment_id':v['id'],'phase':phase,'status':v['status'],'plan_hash':snap.get('study_plan_hash',snap.get('runtime_plan_hash')),
            'positions':len(v.get('positions',[])),'decisions':sum(counts.values()),'quality_counts':dict(counts),'quality':'Descriptive Only' if not counts else None})
    return out,inventory


def boundary_summary(records):
    """異なるPhase/条件をプールせず、配札内→配札の等重み記述。"""
    groups=[]
    for family,group,model,method in sorted({(r['comparison_family'],r['group'],r['model'],r['method']) for r in records if r['quality'] in QUALITY[:2]}):
        rs=[r for r in records if (r['comparison_family'],r['group'],r['model'],r['method'])==(family,group,model,method)]
        features={}
        for key in ('rank_changes','leader_changes','legal_count','reward_difference'):
            ds=defaultdict(list)
            for r in rs:
                if r[key] is not None:ds[r['deal_hash']].append(r[key])
            features[key]=stats([float(np.mean(x)) for x in ds.values()])
        for n in (16,32,64,128):
            ds=defaultdict(list)
            for r in rs:
                t=r['checkpoints'][str(n)]
                if t and t['top_gap'] is not None:ds[r['deal_hash']].append(t['top_gap'])
            features['gap_'+str(n)]=stats([float(np.mean(x)) for x in ds.values()])
        groups.append({'family':family,'group':group,'model':model,'method':method,'decisions':len(rs),'independent_deals':len({r['deal_hash'] for r in rs}),
            'features':features,'periods':dict(Counter(r['period'] for r in rs)),'score_classes':dict(Counter(r['score_class'] for r in rs))})
    return {'groups':groups,'quality_counts':dict(Counter(r['quality'] for r in records)),
        'warning':'過去Evidenceの探索的記述。発見過程・Phase・系列・条件を混合して自然分岐率や因果効果を推定しない。欠測チェックポイントはnull。'}


def crossed_select(records,c):
    chosen=[];cells=[];used=set();per_deal=Counter()
    for label in PERIODS:
        for cls in CLASSES:
            planned=any(normalized(rp)==label for rp in c.campaign_periods)
            pool=[]
            for r in records:
                for origin in r.get('origins',[r]):
                    rr={**r,**origin}
                    if normalized(rr['period'])==label and score_class(rr['game_scores'],rr['player'])==cls:pool.append(rr)
            eligible=[r for r in pool if r['position_hash'] not in used and per_deal[r['deal_hash']]<c.positions_per_deal]
            picked=min(eligible,key=lambda r:(per_deal[r['deal_hash']],c.collectors.index(r['source']),r['deal_id'],r['player'],r['position_hash'])) if planned and eligible and len(chosen)<c.max_positions else None
            cell={'period':label,'score_class':cls,'target':1 if planned else 0,'candidate_observations':len(pool),
                'collection_target':int(any(normalized(period(t))==label for t in c.turns)),
                'candidate_deals':len({r['deal_hash'] for r in pool}),'collection_success':bool(pool),
                'collection_missing':int(any(normalized(period(t))==label for t in c.turns) and not pool),
                'status':'selected' if picked else 'not_planned' if not planned else 'quota_limit' if pool and (not eligible or len(chosen)>=c.max_positions) else 'collection_missing',
                'position_hash':picked['position_hash'] if picked else None,'deal_hash':picked['deal_hash'] if picked else None}
            cells.append(cell)
            if picked:
                used.add(picked['position_hash']);per_deal[picked['deal_hash']]+=1;chosen.append({**picked,'crossed_cell':label+':'+cls})
    return chosen,cells


def crossed_report(v,records,complete):
    cells=[];criteria=CampaignCriteria();positions=v['positions']
    for cell in (v.get('collection_summary') or {}).get('crossed_cells',[]):
        rs=[r for r in records if r['position_hash']==cell['position_hash']];methods=[]
        for method in ('Gap-Adaptive','Uncertainty-Adaptive'):
            xs=[r for r in rs if r['method']==method];ds=defaultdict(list)
            for r in xs:ds[r['deal_hash']].append(r)
            vals={k:[float(np.mean([r[k] for r in rows])) for rows in ds.values()] for k in ('diverged','early_stop','reward_difference','wall_difference')}
            methods.append({'method':method,'decisions':len(xs),'early_stops':sum(r['early_stop'] for r in xs),'divergences':sum(r['diverged'] for r in xs),
                'independent_deals':len(ds),'metrics':{k:stats(x) for k,x in vals.items()},'divergence_interval':rate_interval(vals['diverged'],2) if vals['diverged'] else None,
                'wall_interval':interval(vals['wall_difference'],criteria,cell['period']+cell['score_class']+method+':wall'),
                'reward_interval':interval(vals['reward_difference'],criteria,cell['period']+cell['score_class']+method+':reward')})
        cells.append({**cell,'evaluated':bool(rs),'missing':int(cell['target']>0 and cell['status']!='selected'),'methods':methods,'evidence':rs})
    return {'complete':complete,'cells':cells,'evaluated_deals':len({p['deal_hash'] for p in positions}),'evaluated_positions':len(positions),
        'same_period_comparisons':[p for p in PERIODS if len({r['score_class'] for r in records if r['period']==p})>1],
        'same_score_comparisons':[s for s in CLASSES if len({r['period'] for r in records if r['score_class']==s})>1],
        'warning':'交差セルの探索的選別標本。セル成功率は自然出現確率ではない。収集元・配札・観測者による交絡が残る。未完了時は部分Evidenceのみ。',
        'summary':boundary_summary(records) if complete else None}
