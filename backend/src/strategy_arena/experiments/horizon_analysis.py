"""最大予算の共通経路から停止判断を再構成。将来の標本は判断へ戻さない。"""
from collections import Counter,defaultdict
from copy import deepcopy
from dataclasses import asdict
from time import perf_counter
import numpy as np
from .adaptive_analysis import METHODS,select,stopping,ranked,cost,sample_table,table,execution_meter,selection_observer
from .stopping_analysis import checkpoint,trace_sink,classify_stop,rate_interval
from .runner import derived_seed
from .reliability_analysis import reward_pair
from .evaluation_statistics import fixed_evidence

KEYS=('derived_games','simulated_turns','simulated_player_actions','elapsed_seconds')

def reconstruct(obs,path,budget,method,c):
    if budget>path['budget'] or budget<16:raise ValueError('経路にない予算')
    trace=[];first=None
    for raw in path['trace']:
        if raw['worlds']>budget:break
        t=deepcopy(raw);reason=stopping(method,t['contrasts'],c);t['stop_reason']=reason
        trace.append(checkpoint(t,{'budget':budget,'effective_cap':budget},c))
        if reason:first=t['worlds'];break
    if not trace or (first is None and trace[-1]['worlds']!=budget):raise ValueError('チェックポイント不足')
    t=trace[-1];n=t['worlds'];reason=t['stop_reason'] or 'max_worlds';trace[-1]['stop_reason']=reason
    rows=sorted(t['candidates'],key=lambda r:(r['card']['rank'],r['card']['suit']))
    full_first=next((r['worlds'] for r in path['trace'] if stopping(method,r['contrasts'],c)),None)
    changes=[];previous=t['selected_card']
    for later in path['trace']:
        if later['worlds']<=n:continue
        if later['selected_card']!=previous:changes.append({'worlds':later['worlds'],'from':previous,'to':later['selected_card']})
        previous=later['selected_card']
    counter=cost(obs,obs.legal_actions,n,None)
    result={'method':method,'model':path['model'],'repeat':path['repeat'],'seed':path['seed'],'budget':budget,'effective_cap':budget,
      'selected_card':t['selected_card'],'self_middle_card':ranked(rows,'immediate_middle')[0]['card'],'candidates':rows,'trace':trace,
      'stop_reason':reason,'early_stop':n<budget,'max_budget_reached':n==budget,'cost':counter,'counterfactual_policy_cost':counter,
      'first_condition_worlds':first,'condition_before_cap':first is not None and first<budget,
      'first_condition_full_research_path':full_first,'actual_stop_worlds':n,
      'post_stop_fixed_changes':changes if n<budget else [],'post_stop_scope':'研究用のみ。停止判断へ使用しない。'}
    result['classification']=classify_stop(result)
    return result

def analyze_horizon(obs,c,pid,check=lambda:None,progress=lambda:None):
    started=perf_counter();cards=tuple(sorted(obs.legal_actions));rows=[];paths=[];sessions=[]
    stages={s:derived_seed(c.policy_seed if s=='policy' else 1000000+c.validation_offset,f'adaptive-v1:{pid}:{s}') for s in ('policy','reference','final')}
    assert len(set(stages.values()))==3
    meter=execution_meter.get();sink=trace_sink.get()
    def observer(meta,event,value):
        if event=='started':
            entry={**meta,'position_hash':pid,'role':'actual_research_path','selection_completed':False,'classification':'in_progress','checkpoints':[]}
            sessions.append(entry)
            if sink:sink(entry)
        elif event=='checkpoint':sessions[-1]['checkpoints'].append(checkpoint(value,meta,c))
        else:sessions[-1].update(selection_completed=True,classification='completed_fixed_budget',cost=value['cost'],selected_card=value['selected_card'])
    token=selection_observer.set(observer)
    try:
        if meter:meter['stage']='policy'
        for model in c.models:
            for repeat in range(c.repeats):
                seed=derived_seed(stages['policy'],f'repeat:{repeat}')
                path=select(obs,cards,model,seed,max(c.budgets),'Fixed',c,check,progress);path['repeat']=repeat;paths.append(path)
                for b in c.budgets:
                    for method in METHODS:rows.append(reconstruct(obs,path,b,method,c))
    finally:selection_observer.reset(token)
    reference={};final={};overhead=[];family=10000
    for model in c.models:
        if meter:meter['stage']='reference'
        rs,rc=sample_table(obs,cards,model,stages['reference'],c.reference_worlds,check,progress)
        ref=ranked(table(cards,rs))[0]['card'];reference[model]={'card':ref,'seed':stages['reference'],'cost':rc,'candidates':table(cards,rs)}
        if meter:meter['stage']='final'
        fs,fc=sample_table(obs,cards,model,stages['final'],c.final_worlds,check,progress)
        final[model]={'seed':stages['final'],'cost':fc,'candidates':table(cards,fs)};overhead.extend([rc,fc])
        for r in rows:
            if r['model']!=model:continue
            f=next(x for x in rows if x['model']==model and x['repeat']==r['repeat'] and x['budget']==r['budget'] and x['method']=='Fixed')
            chosen=r['selected_card'];sc=f['self_middle_card']
            r['fixed_horizon_card']=f['selected_card']
            r['evaluations']=[{'model':model,'value':next(x['reward'] for x in final[model]['candidates'] if x['card']==chosen),
               'reference_card':ref,'self_middle_card':sc,'minus_fixed':reward_pair(cards,fs,chosen,f['selected_card'],family),
               'minus_self':reward_pair(cards,fs,chosen,sc,family),'estimated_regret':reward_pair(cards,fs,ref,chosen,family),
               'matches_fixed':chosen==f['selected_card']}]
    selection={k:sum(p['cost'][k] for p in paths) for k in KEYS};extra={k:sum(p[k] for p in overhead) for k in KEYS}
    total={k:selection[k]+extra[k] for k in KEYS}
    return {'rows':rows,'research_paths':paths,'stopping_sessions':sessions,'reference':reference,'final':final,'stage_seeds':stages,
      'selection_cost':selection,'overhead_cost':extra,'total_cost':total,'actual_research_compute_cost':total,
      'elapsed_seconds':perf_counter()-started,'legal_count':len(cards),'scope':'反実仮想コストの秒数は未計測(null)。実測は最大経路＋独立参照・最終評価。参照札は真の最適手ではない。'}

def horizon_summary(positions):
    buckets=defaultdict(lambda:defaultdict(list))
    for p in positions:
        a=p['adaptive']
        for r in a['rows']:
            e=r['evaluations'][0];k=a['legal_count'];n=r['cost']['hidden_worlds']
            values={'reward':e['value'],'reward_difference':e['minus_fixed']['mean'],'minus_self':e['minus_self']['mean'],
              'estimated_regret':e['estimated_regret']['mean'],'early_stop_rate':int(r['early_stop']),'max_budget_rate':int(r['max_budget_reached']),
              'condition_met_rate':int(r['first_condition_worlds'] is not None),'condition_before_cap_rate':int(r['condition_before_cap']),
              'matches_fixed':int(e['matches_fixed']),'used_worlds':n,'derived_games':k*n,'derived_games_difference':k*(n-r['budget']),
              'simulated_turns':r['cost']['simulated_turns'],'simulated_turns_difference':k*(n-r['budget'])*(15-p['turn'])}
            for label in ('all',p['stratum']['class'],p['period'],f'legal:{k}',f'remaining:{15-p["turn"]}'):
                buckets[(r['method'],r['model'],r['budget'],label)][p['deal_hash']].append((p['position_hash'],values))
    out=[]
    for (method,model,budget,label),deals in buckets.items():
        ds={}
        for key in next(iter(deals.values()))[0][1]:
            values=[]
            for entries in deals.values():
                by=defaultdict(list)
                for pid,v in entries:by[pid].append(v[key])
                values.append(float(np.mean([np.mean(x) for x in by.values()])))
            ds[key]=values
        out.append({'method':method,'model':model,'budget':budget,'stratum':label,'independent_deals':len(deals),
          'positions':len({pid for entries in deals.values() for pid,_ in entries}),**{k:float(np.mean(v)) for k,v in ds.items()},
          'early_stop_interval':rate_interval(ds['early_stop_rate'],10000),
          'reward_difference_evidence':fixed_evidence(ds['reward_difference'],completed=True,comparisons=10000,bound=4),
          'cost_difference_evidence':fixed_evidence(ds['derived_games_difference'],completed=True,comparisons=10000,bound=4352),
          'analysis_role':'primary' if method=='Gap-Adaptive' and budget==128 and label=='all' else 'secondary',
          'cost_scope':'counterfactual_policy_cost。時間は推定しない。反復→局面→配札平均。'})
    return out
