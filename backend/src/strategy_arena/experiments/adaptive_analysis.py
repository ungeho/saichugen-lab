"""局面内適応と独立した参照選択・最終評価。既存のRolloutだけを呼ぶ。"""
from collections import defaultdict
from contextvars import ContextVar
from dataclasses import asdict
from math import sqrt
from time import perf_counter
import numpy as np
from .runner import derived_seed
from .reliability_analysis import reward_pair, distribution
from .middle_analysis import fixed_evidence
from .evaluation_statistics import fixed_evidence as deal_evidence
from .stratification_analysis import extra_outcome
from ..rollouts import rollout_trial
from ..strategies.registry import create_strategy

METHODS=('Fixed','Gap-Adaptive','Uncertainty-Adaptive')
execution_meter=ContextVar('adaptive_execution_meter',default=None)

def table(cards,samples):
    return [{'card':asdict(card),'trials':len(values),'reward':float(np.mean([v['reward'] for v in values])),
             'immediate_middle':float(np.mean([v['immediate_middle'] for v in values]))} for card,values in zip(cards,samples)]

def ranked(rows,key='reward'):
    return sorted(rows,key=lambda r:(-r[key],r['card']['rank'],r['card']['suit']))

def gap_statistics(cards,samples):
    rows=ranked(table(cards,samples));indices={tuple(asdict(c).values()):i for i,c in enumerate(cards)}
    a=indices[tuple(rows[0]['card'].values())];contrasts=[]
    for r in rows[1:]:
        b=indices[tuple(r['card'].values())];diff=[x['reward']-y['reward'] for x,y in zip(samples[a],samples[b])]
        contrasts.append({'card':r['card'],'gap':float(np.mean(diff)),
                          'se':float(np.std(diff,ddof=1)/sqrt(len(diff))) if len(diff)>1 else None})
    return rows,contrasts

def stopping(method,contrasts,c):
    if method=='Fixed':return None
    if not contrasts:return 'single_legal_action'
    if method=='Gap-Adaptive' and contrasts[0]['gap']>c.gap_threshold:return 'gap_threshold'
    if method=='Uncertainty-Adaptive' and all(x['se'] is not None and x['gap']>c.uncertainty_z*x['se']+c.minimum_gap for x in contrasts):return 'exploratory_paired_se'
    return None

def draw(obs,cards,model,seed,trial,check,progress):
    meter=execution_meter.get()
    def on_game(event):
        if meter is None:return
        stage=meter['stage'];m=meter[stage]
        if event=='started':
            if sum(meter[s]['started_games'] for s in ('policy','reference','final'))>=meter['limit']:raise InterruptedError('BudgetExceeded')
            m['started_games']+=1
        else:
            m['completed_games']+=1;m['completed_simulated_turns']+=15-obs.turn
    rows=rollout_trial(obs,cards,[create_strategy(model) for _ in range(3)],seed,trial,check,
                       policy_names=(model,)*3,outcome_hook=extra_outcome,on_game=on_game)
    progress();return rows

def cost(obs,cards,worlds,seconds):
    games=len(cards)*worlds
    return {'legal_count':len(cards),'hidden_worlds':worlds,'candidate_rollouts':worlds,'derived_games':games,
            'simulated_turns':games*(15-obs.turn),'simulated_player_actions':games*(15-obs.turn)*3,'elapsed_seconds':seconds}

def select(obs,cards,model,seed,budget,method,c,check=lambda:None,progress=lambda:None):
    cards=tuple(sorted(cards));cap=budget if c.budget_mode=='max_worlds' else min(budget,c.games_per_policy//len(cards))
    if cap<c.initial_worlds:raise ValueError('全合法手の初期評価に必要な総派生対局予算がありません')
    samples=[[] for _ in cards];trace=[];started=perf_counter();reason=None
    for trial in range(cap):
        check()
        for i,value in enumerate(draw(obs,cards,model,seed,trial,check,progress)):samples[i].append(value)
        n=trial+1
        if n<c.initial_worlds or (n!=c.initial_worlds and n%c.batch_worlds and n!=cap):continue
        rows,contrasts=gap_statistics(cards,samples)
        reason=stopping(method,contrasts,c)
        trace.append({'worlds':n,'selected_card':rows[0]['card'],'estimated_reward':rows[0]['reward'],
                      'gap':contrasts[0]['gap'] if contrasts else 0,'paired_se':contrasts[0]['se'] if contrasts else 0,
                      'contrasts':contrasts,'stop_reason':reason,'candidates':rows})
        if reason:break
    n=len(samples[0]);reason=reason or ('total_game_cap' if cap<budget else 'max_worlds')
    trace[-1]['stop_reason']=reason;rows=table(cards,samples)
    return {'method':method,'model':model,'budget':budget,'seed':seed,'effective_cap':cap,'stop_reason':reason,
            'early_stop':n<cap,'max_budget_reached':n==budget,'selected_card':ranked(rows)[0]['card'],
            'self_middle_card':ranked(rows,'immediate_middle')[0]['card'],'candidates':rows,'trace':trace,
            'cost':cost(obs,cards,n,perf_counter()-started)}

def sample_table(obs,cards,model,seed,worlds,check,progress):
    started=perf_counter();samples=[[] for _ in cards]
    for trial in range(worlds):
        check()
        for i,value in enumerate(draw(obs,cards,model,seed,trial,check,progress)):samples[i].append(value)
    return samples,cost(obs,cards,worlds,perf_counter()-started)

def analyze_adaptive(obs,c,pid,check=lambda:None,progress=lambda:None):
    cards=tuple(sorted(obs.legal_actions));started=perf_counter();rows=[]
    stages={s:derived_seed(c.policy_seed if s=='policy' else 1000000+c.validation_offset,f'adaptive-v1:{pid}:{s}') for s in ('policy','reference','final')}
    if len(set(stages.values()))!=3:raise ValueError('独立系列seedが衝突しました')
    meter=execution_meter.get()
    if meter is not None:meter['stage']='policy'
    for model in c.models:
        for repeat in range(c.repeats):
            seed=derived_seed(stages['policy'],f'repeat:{repeat}')
            for budget in c.budgets:
                for method in METHODS:
                    row=select(obs,cards,model,seed,budget,method,c,check,progress);row['repeat']=repeat;rows.append(row)
    reference={};final={};overhead=[];family=c.max_positions*len(c.models)*c.repeats*len(c.budgets)*len(METHODS)*12
    for model in c.models:
        if meter is not None:meter['stage']='reference'
        reference_samples,reference_cost=sample_table(obs,cards,model,stages['reference'],c.reference_worlds,check,progress)
        ref=ranked(table(cards,reference_samples))[0]['card']
        if meter is not None:meter['stage']='final'
        final_samples,final_cost=sample_table(obs,cards,model,stages['final'],c.final_worlds,check,progress)
        reference[model]={'card':ref,'seed':stages['reference'],'cost':reference_cost,'candidates':table(cards,reference_samples)}
        final[model]={'seed':stages['final'],'cost':final_cost,'candidates':table(cards,final_samples)}
        overhead.extend([reference_cost,final_cost])
        for row in rows:
            if not c.cross_models and row['model']!=model:continue
            fixed=next(r for r in rows if r['model']==row['model'] and r['repeat']==row['repeat'] and r['budget']==row['budget'] and r['method']=='Fixed')
            chosen=row['selected_card'];self_card=fixed['self_middle_card']
            value=next(r for r in final[model]['candidates'] if r['card']==chosen)['reward']
            row.setdefault('evaluations',[]).append({'model':model,'value':value,'reference_card':ref,'self_middle_card':self_card,
                'reward_evidence':fixed_evidence(next(([v['reward'] for v in final_samples[i]] for i,card in enumerate(cards) if asdict(card)==chosen)),completed=True,comparisons=family,bound=2),
                'minus_fixed':reward_pair(cards,final_samples,chosen,fixed['selected_card'],family),
                'minus_self':reward_pair(cards,final_samples,chosen,self_card,family),
                'estimated_regret':reward_pair(cards,final_samples,ref,chosen,family),
                'matches_fixed':chosen==fixed['selected_card']})
    frequencies=[{'model':model,'budget':budget,'method':method,**distribution(cards,[r['selected_card'] for r in rows if r['model']==model and r['budget']==budget and r['method']==method])}
                 for model in c.models for budget in c.budgets for method in METHODS]
    keys=('derived_games','simulated_turns','simulated_player_actions','elapsed_seconds')
    selection_cost={k:sum(r['cost'][k] for r in rows) for k in keys};overhead_cost={k:sum(r[k] for r in overhead) for k in keys}
    return {'rows':rows,'frequencies':frequencies,'reference':reference,'final':final,'stage_seeds':stages,
            'selection_cost':selection_cost,'overhead_cost':overhead_cost,'total_cost':{k:selection_cost[k]+overhead_cost[k] for k in keys},
            'elapsed_seconds':perf_counter()-started,'legal_count':len(cards),
            'scope':'局面内適応。停止のSEは探索的な目安で逐次有効区間ではない。参照札は有限標本でありRegretは負になり得る。Self-Middleは対応Fixed選択標本の直近中位率最大札。'}

def adaptive_summary(positions):
    buckets=defaultdict(lambda:defaultdict(list))
    for p in positions:
        a=p['adaptive'];labels=['all',p['stratum']['class'],p['period'],f'legal:{a["legal_count"]}']
        if p['stratum']['strict_middle']:labels.extend([p['stratum']['relation']]+[k for k in ('both_small','both_large') if p['stratum'][k]])
        for r in a['rows']:
            for e in r['evaluations']:
                values={'reward':e['value'],'minus_fixed':e['minus_fixed']['mean'],'minus_self':e['minus_self']['mean'],'estimated_regret':e['estimated_regret']['mean'],
                        'derived_games':r['cost']['derived_games'],'simulated_turns':r['cost']['simulated_turns'],'elapsed_seconds':r['cost']['elapsed_seconds'],
                        'early_stop':int(r['early_stop']),'max_budget_reached':int(r['max_budget_reached']),'matches_fixed':int(e['matches_fixed'])}
                for label in labels:buckets[(p['population'],r['model'],e['model'],r['method'],r['budget'],label)][p['deal_hash']].append((p['position_hash'],values))
    out=[]
    for (population,model,evaluation,method,budget,label),deals in buckets.items():
        metrics={};diff=[]
        for metric in next(iter(deals.values()))[0][1]:
            ds=[]
            for entries in deals.values():
                by=defaultdict(list)
                for pid,v in entries:by[pid].append(v[metric])
                ds.append(float(np.mean([np.mean(v) for v in by.values()])))
            metrics[metric]=float(np.mean(ds))
            if metric=='minus_fixed':diff=ds
        out.append({'population':population,'model':model,'evaluation_model':evaluation,'method':method,'budget':budget,'stratum':label,
                    'independent_deals':len(deals),'positions':len({pid for entries in deals.values() for pid,_ in entries}),**metrics,
                    'deal_evidence':deal_evidence(diff,completed=True,comparisons=10000,bound=4),
                    'scope':'反復→局面→実配札を等重み。診断と新規、評価モデル、層を合算しない。探索的記述。'})
    return out
