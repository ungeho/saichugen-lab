"""事前tuple抽出と、配札内の対応組。H1の入力は16世界だけ。"""
from collections import Counter,defaultdict
from itertools import combinations
import numpy as np
from .divergence_coverage import score_class,CLASSES
from .campaign_analysis import PERIODS,CampaignCriteria,interval
from .calibration_coverage import normalized
from .noise_analysis import stats
from .stopping_analysis import rate_interval


def legal_bucket(n):return '1-8' if 1<=n<=8 else '9-17'


def matched_select(records,c):
    selected=[];slots=[];coverage=[]
    projected=[{**r,**o} for r in records for o in r.get('origins',[r])]
    for i,source in enumerate(c.matched_sources):
        seed=str(c.start_offset+i)
        for p in dict.fromkeys(c.campaign_periods):
            for cls in c.matched_scores:
                pool=[r for r in projected if r['deal_id']==seed and r['source']==source and normalized(r['period'])==p and score_class(r['game_scores'],r['player'])==cls]
                picked=min(pool,key=lambda r:(r['player'],r['position_hash'])) if pool else None
                slots.append({'deal_id':seed,'source':source,'period':p,'score_class':cls,'candidate_observations':len(pool),'status':'selected' if picked else 'collection_missing','position_hash':picked['position_hash'] if picked else None})
                if picked:selected.append({**picked,'population':'fresh','seed_partition':c.partition})
    for p in PERIODS:
        for cls in CLASSES:
            for source in c.collectors:
                pool=[r for r in projected if normalized(r['period'])==p and r['source']==source and score_class(r['game_scores'],r['player'])==cls]
                coverage.append({'period':p,'score_class':cls,'source':source,'candidate_observations':len(pool),'candidate_deals':len({r['deal_hash'] for r in pool}),
                    'requested':sum(s['source']==source and s['period']==p and s['score_class']==cls for s in slots),
                    'selected':sum(s['source']==source and s['period']==p and s['score_class']==cls and s['status']=='selected' for s in slots)})
    return selected,slots,coverage


def matched_report(v,records,complete):
    c=v['config'];points=[{**r,'deal_id':next(p['deal_id'] for p in v['positions'] if p['position_hash']==r['position_hash'])} for r in records if r['method']=='Fixed'];criteria=CampaignCriteria();pairs=[]
    slots=(v.get('collection_summary') or {}).get('matched_slots',[])
    periods=list(dict.fromkeys(c['campaign_periods']));sources=list(dict.fromkeys(c['matched_sources']))
    # 各比較を同一配札/モデル/反復/世界数/合法手区分で固定する。
    for seed in range(c['start_offset'],c['start_offset']+c['deals']):
        for axis in ('score_class','period','source'):
            levels=c['matched_scores'] if axis=='score_class' else periods if axis=='period' else sources
            for left,right in combinations(levels,2):
                other_a=periods if axis=='score_class' else c['matched_scores']
                other_b=[c['matched_sources'][seed-c['start_offset']]] if axis in ('score_class','period') else periods
                for a in other_a:
                    for b in other_b:
                        for model in c['models']:
                            def find(level):
                                return next((r for r in points if r['deal_id']==str(seed) and r['model']==model and r['repeat']==0 and r[axis]==level and
                                    (r['period']==a and r['source']==b if axis=='score_class' else r['score_class']==a and r['source']==b if axis=='period' else r['score_class']==a and r['period']==b)),None)
                            x,y=find(left),find(right)
                            for n in (16,32,64,128):
                                tx=x['checkpoints'][str(n)] if x else None;ty=y['checkpoints'][str(n)] if y else None
                                reason=None
                                if x is None or y is None:
                                    def requested(level):
                                        return {'period':a,'source':b,'score_class':level} if axis=='score_class' else {'score_class':a,'source':b,'period':level} if axis=='period' else {'score_class':a,'period':b,'source':level}
                                    missing_levels=[level for level,point in ((left,x),(right,y)) if point is None]
                                    collection_missing=any(s['deal_id']==str(seed) and s['status']=='collection_missing' and all(s[k]==value for k,value in requested(level).items()) for level in missing_levels for s in slots)
                                    reason='not_evaluated' if not slots else 'collector_not_assigned' if axis=='source' else 'collection_missing' if collection_missing else 'not_evaluated'
                                elif legal_bucket(x['legal_count'])!=legal_bucket(y['legal_count']):reason='legal_bucket_mismatch'
                                elif tx is None or ty is None or tx['top_gap'] is None or ty['top_gap'] is None:reason='missing_checkpoint'
                                pairs.append({'axis':axis,'left':left,'right':right,'deal_id':str(seed),'model':model,'repeat':0,'worlds':n,'fixed_conditions':[a,b],
                                    'matched':reason is None,'reason':reason,'difference':ty['top_gap']-tx['top_gap'] if reason is None else None,
                                    'left_legal_count':x['legal_count'] if x else None,'right_legal_count':y['legal_count'] if y else None,
                                    'left_position':x['position_hash'] if x else None,'right_position':y['position_hash'] if y else None})
    h1=[]
    for r in points:
        t=r['checkpoints']['16'];last=r['checkpoints']['128']
        h1.append({'deal_hash':r['deal_hash'],'position_hash':r['position_hash'],'model':r['model'],'period':r['period'],'score_class':r['score_class'],'source':r['source'],
            'gap16':t['top_gap'] if t else None,'small_gap':t['top_gap']<=c['small_gap_threshold'] if t and t['top_gap'] is not None else None,
            'changed_at_128':t['selected_card']!=last['selected_card'] if t and last else None,'any_leader_change':r['leader_changes']>0 if t and last and r['leader_changes'] is not None else None,
            'feature_scope':'16世界のみ','outcome_scope':'32〜128世界の事後結果。入力へ戻さない。'})
    summaries=[];hgroups=[]
    if complete:
        for axis,left,right,n,conditions in sorted({(r['axis'],r['left'],r['right'],r['worlds'],tuple(r['fixed_conditions'])) for r in pairs}):
            rs=[r for r in pairs if (r['axis'],r['left'],r['right'],r['worlds'],tuple(r['fixed_conditions']))==(axis,left,right,n,conditions)];ds=defaultdict(list)
            for r in rs:
                if r['matched']:ds[r['deal_id']].append(r['difference'])
            values=[float(np.mean(x)) for x in ds.values()]
            summaries.append({'axis':axis,'left':left,'right':right,'worlds':n,'fixed_conditions':list(conditions),'model_weighting':'3モデルを配札内で等重み','matched':sum(r['matched'] for r in rs),'unmatched':sum(not r['matched'] for r in rs),
                'reasons':dict(Counter(r['reason'] for r in rs if r['reason'])),'independent_deals':len(ds),'difference':stats(values),'interval':interval(values,criteria,'matched:'+axis+left+right+str(n))})
        for small in (True,False):
            ds=defaultdict(list);endpoints=defaultdict(list)
            for r in h1:
                if r['small_gap']==small and r['any_leader_change'] is not None:
                    ds[r['deal_hash']].append(int(r['any_leader_change']));endpoints[r['deal_hash']].append(int(r['changed_at_128']))
            values=[float(np.mean(x)) for x in ds.values()]
            hgroups.append({'small_gap':small,'independent_deals':len(ds),'observations':sum(len(x) for x in ds.values()),'leader_change_rate':stats(values),'endpoint_change_rate':stats([float(np.mean(x)) for x in endpoints.values()]),'interval':rate_interval(values,2)})
    return {'complete':complete,'slots':slots,'coverage':(v.get('collection_summary') or {}).get('matched_coverage',[]),'pairs':pairs,
        'matching_summary':summaries if complete else None,'matched':sum(r['matched'] for r in pairs),'unmatched':sum(not r['matched'] and r['reason']!='not_evaluated' for r in pairs),'pending':sum(r['reason']=='not_evaluated' for r in pairs),
        'h1_records':h1,'h1_summary':hgroups if complete else None,'small_gap_threshold':c['small_gap_threshold'],
        'warning':'条件付き選別標本。配札内対応・合法手区分1–8/9–17。区分内の枚数差と未観測交絡は残る。マッチ不成立から効果を推定しない。H1は未知配札の予測性能を証明しない。'}
