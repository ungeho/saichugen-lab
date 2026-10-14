"""既存の停止判断を変更せず、構成要素・実配札単位の不確実性を記述する。"""
from collections import Counter,defaultdict
from copy import deepcopy
from dataclasses import asdict
from math import log,sqrt
from contextvars import ContextVar
from inspect import getsource
import numpy as np
from .adaptive_analysis import stopping,ranked,gap_statistics,analyze_adaptive,selection_observer
from .evolution import digest
from .runner import derived_seed
from .evaluation_statistics import fixed_evidence

trace_sink=ContextVar('stopping_trace_sink',default=None)

def rule_fingerprint():
    return digest({'stopping':getsource(stopping),'ranking':getsource(ranked),'paired_gaps':getsource(gap_statistics),
                   'initial_worlds':16,'batch_worlds':16,'gap_threshold':.5,'uncertainty_z':2.,'minimum_gap':.05,
                   'tie':'rank,suit ascending','version':'phase32-frozen-v1'})

def classify_stop(row):
    if row['early_stop']:return 'early_stop'
    if row['effective_cap']<row['budget']:return 'max_derived_games'
    if row['method']=='Fixed':return 'completed_fixed_budget'
    return 'max_worlds'

def checkpoint(value,meta,c):
    t=deepcopy(value);contrasts=t['contrasts']
    margins=[{**r,'required_gap':None if r['se'] is None else c.uncertainty_z*r['se']+c.minimum_gap,
              'margin':None if r['se'] is None else r['gap']-c.uncertainty_z*r['se']-c.minimum_gap} for r in contrasts]
    enough=all(r['se'] is not None for r in contrasts)
    gap_margin=t['gap']-c.gap_threshold
    t.update(components={'initial_samples_ready':t['worlds']>=c.initial_worlds,'gap_threshold':c.gap_threshold,
              'gap_margin':gap_margin,'gap_condition':bool(contrasts) and gap_margin>0,
              'uncertainty_z':c.uncertainty_z,'minimum_gap':c.minimum_gap,'uncertainty_components':margins,
              'uncertainty_condition':bool(contrasts) and enough and all(r['margin']>0 for r in margins),
              'minimum_conjunction_margin':min((r['margin'] for r in margins),default=None) if enough else None,
              'single_candidate':not contrasts},
             condition_met=t['stop_reason'] is not None,
             additional_sampling=t['stop_reason'] is None and t['worlds']<meta['effective_cap'],
             max_worlds_reached=t['worlds']==meta['budget'],effective_cap_reached=t['worlds']==meta['effective_cap'])
    return t

def analyze_stopping(obs,c,pid,check=lambda:None,progress=lambda:None):
    sessions=[];sink=trace_sink.get()
    root=derived_seed(c.policy_seed,f'adaptive-v1:{pid}:policy')
    repeat_lookup={derived_seed(root,f'repeat:{r}'):r for r in range(c.repeats)}
    def observer(meta,event,value):
        key=(meta['model'],meta['seed'],meta['budget'],meta['method'])
        if event=='started':
            entry={**meta,'position_hash':pid,'repeat':repeat_lookup[meta['seed']],'legal_count':len(obs.legal_actions),
                   'remaining_turns':15-obs.turn,'remaining_rounds':5-obs.turn//3,'checkpoints':[],
                   'classification':'in_progress','selected_card':None,'selection_completed':False}
            sessions.append(entry)
            if sink is not None:sink(entry)
        else:
            entry=next(r for r in reversed(sessions) if (r['model'],r['seed'],r['budget'],r['method'])==key)
            if event=='checkpoint':entry['checkpoints'].append(checkpoint(value,meta,c))
            else:
                entry.update(classification=classify_stop(value),selected_card=value['selected_card'],raw_stop_reason=value['stop_reason'],
                             selection_completed=True,max_budget_reached=value['max_budget_reached'],cost=value['cost'])
                entry['checkpoints'][-1].update(final_selected_card=value['selected_card'],final_stop_reason=entry['classification'])
    token=selection_observer.set(observer)
    try:result=analyze_adaptive(obs,c,pid,check,progress)
    finally:selection_observer.reset(token)
    result['stopping_sessions']=sessions
    return result

def select_validation_positions(records,limit):
    """事前固定した進行時点巡回。実配札・得点層・収集元を均す。結果には依存しない。"""
    chosen=[];used=set();deals=Counter();classes=Counter();sources=Counter()
    periods=('early','middle','before_final_round','final_round')
    normalized=lambda r:'final_round' if r['period']=='final_round_start' else r['period']
    while len(chosen)<limit:
        added=False
        for period in periods:
            options=[r for r in records if r['position_hash'] not in used and normalized(r)==period]
            if not options:continue
            r=min(options,key=lambda r:(deals[r['deal_hash']],classes[r['stratum']['class']],sources[r['source']],r['position_hash']))
            chosen.append(r);used.add(r['position_hash']);deals[r['deal_hash']]+=1;classes[r['stratum']['class']]+=1;sources[r['source']]+=1;added=True
            if len(chosen)==limit:break
        if not added:break
    return chosen

def rate_interval(values,comparisons):
    n=len(values)
    if not n:return None
    mean=float(np.mean(values));radius=sqrt(log(2*comparisons/.05)/(2*n))
    return [max(0.,mean-radius),min(1.,mean+radius)]

def stopping_summary(positions):
    buckets=defaultdict(lambda:defaultdict(list));family=10000
    for p in positions:
        a=p['adaptive'];labels=['all',p['stratum']['class'],p['period'],f'legal:{a["legal_count"]}',f'remaining:{15-p["turn"]}']
        if p['stratum']['strict_middle']:labels.extend([p['stratum']['relation']]+[k for k in ('both_small','both_large') if p['stratum'][k]])
        for r in a['rows']:
            fixed=next(x for x in a['rows'] if x['model']==r['model'] and x['budget']==r['budget'] and x['repeat']==r['repeat'] and x['method']=='Fixed')
            e=next(x for x in r['evaluations'] if x['model']==r['model']);costdiff=r['cost']['derived_games']-fixed['cost']['derived_games']
            values={'early_stop_rate':int(r['early_stop']),'max_budget_rate':int(r['max_budget_reached']),
                    'derived_games':r['cost']['derived_games'],'derived_games_difference':costdiff,'simulated_turns':r['cost']['simulated_turns'],
                    'simulated_turns_difference':r['cost']['simulated_turns']-fixed['cost']['simulated_turns'],
                    'elapsed_seconds':r['cost']['elapsed_seconds'],'reward':e['value'],'reward_difference':e['minus_fixed']['mean'],
                    'minus_self':e['minus_self']['mean'],'estimated_regret':e['estimated_regret']['mean']}
            subset='reduced_only' if costdiff<0 else 'not_reduced_only'
            for label in labels+[subset]:buckets[(r['method'],r['model'],r['budget'],label)][p['deal_hash']].append((p['position_hash'],values))
    output=[]
    for (method,model,budget,label),deals in buckets.items():
        per_deal={};means={}
        for metric in next(iter(deals.values()))[0][1]:
            ds=[]
            for rows in deals.values():
                by=defaultdict(list)
                for pid,v in rows:by[pid].append(v[metric])
                ds.append(float(np.mean([np.mean(v) for v in by.values()])))
            per_deal[metric]=ds;means[metric]=float(np.mean(ds))
        output.append({'method':method,'model':model,'budget':budget,'stratum':label,'independent_deals':len(deals),
                       'positions':len({pid for rows in deals.values() for pid,_ in rows}),**means,
                       'worst_derived_games':max(v['derived_games'] for rows in deals.values() for _,v in rows),
                       'early_stop_interval':rate_interval(per_deal['early_stop_rate'],family),
                       'reward_difference_evidence':fixed_evidence(per_deal['reward_difference'],completed=True,comparisons=family,bound=4),
                       'cost_difference_evidence':fixed_evidence(per_deal['derived_games_difference'],completed=True,comparisons=family,bound=4352),
                       'analysis_role':'secondary_postselected' if label in ('reduced_only','not_reduced_only') else 'primary' if label=='all' else 'secondary_stratified',
                       'uncertainty':'配札平均の有界Hoeffding＋Bonferroni。少数配札では広い／報酬差区間未提供。差なしは同等性ではない。'})
    return output
