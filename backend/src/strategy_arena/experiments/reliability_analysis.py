"""ネストした選択標本、独立評価、継続モデルを分離する診断。"""
from collections import Counter,defaultdict
from dataclasses import asdict
from math import log2
from time import perf_counter
import numpy as np
from .decision_analysis import choose_rules,enrich_candidate,RULES
from .stratification_analysis import extra_outcome
from .middle_analysis import fixed_evidence
from .evaluation_statistics import fixed_evidence as deal_evidence
from .metrics import wilson
from .runner import derived_seed
from ..rollouts import rollout_trial
from ..strategies.registry import create_strategy


def candidate_table(obs,cards,samples,family):
    rows=[]
    for card,values in zip(cards,samples):
        scores=Counter(','.join(map(str,v['next_scores'])) for v in values)
        row={'card':asdict(card),'trials':len(values),'next_scores_distribution':dict(scores),
            **{key:float(np.mean([v[key] for v in values])) for key in ('reward','immediate_middle','next_strict_middle','score')},
            'immediate_probabilities':np.mean([v['immediate_probabilities'] for v in values],axis=0).tolist(),
            'reward_sd':float(np.std([v['reward'] for v in values],ddof=1)) if len(values)>1 else None,
            'reward_evidence':fixed_evidence([v['reward'] for v in values],completed=True,comparisons=family,bound=2)}
        rows.append(enrich_candidate(row,obs.player))
    return rows


def reward_pair(cards,samples,left,right,family):
    def index(card):return next(i for i,c in enumerate(cards) if asdict(c)==card)
    if left==right:return {'mean':0.,'interval':[0.,0.],'sd':0.,'independent_world_samples':len(samples[0]),'method':'同じ固定札の差は恒等的に0。','decision':'hold'}
    a,b=index(left),index(right)
    return fixed_evidence([x['reward']-y['reward'] for x,y in zip(samples[a],samples[b])],completed=True,comparisons=family,bound=4)


def distribution(cards,selected):
    n=len(selected);counts=Counter((c['rank'],c['suit']) for c in selected)
    probs=[v/n for v in counts.values()]
    return {'repeats':n,'modal_fraction':max(probs),'entropy_bits':-sum(p*log2(p) for p in probs),
        'pair_disagreement':1-sum(v*(v-1) for v in counts.values())/(n*(n-1)) if n>1 else None,
        'frequencies':[{'card':asdict(c),'count':counts[(c.rank,c.suit)],'fraction':counts[(c.rank,c.suit)]/n,
            'ci95':list(wilson(counts[(c.rank,c.suit)],n))} for c in cards],
        'uncertainty':'少数の独立選択反復。カード別Wilson区間は周辺区間で多重補正なし。最頻札の正しさを示さない。'}


def nested_selection(obs,cards,budgets,model,repeats,seed,family,tolerance=0,check=lambda:None,progress=lambda:None):
    rows=[];templates=[create_strategy(model) for _ in range(3)]
    for repeat in range(repeats):
        stream_seed=derived_seed(seed,f'selection-repeat:{repeat}')
        samples=[[] for _ in cards];started=perf_counter();previous=0;previous_card=None;changes=0
        for trial in range(max(budgets)):
            check()
            for i,value in enumerate(rollout_trial(obs,cards,templates,stream_seed,trial,check,policy_names=(model,)*3,outcome_hook=extra_outcome)):samples[i].append(value)
            progress()
            worlds=trial+1
            if worlds not in budgets:continue
            candidates=candidate_table(obs,cards,samples,family);chosen=choose_rules(candidates,tolerance)
            ranked=sorted(candidates,key=lambda r:(-r['reward'],r['card']['rank'],r['card']['suit']))
            top,nextbest=ranked[0],ranked[1] if len(ranked)>1 else ranked[0]
            if previous_card is not None and chosen['Terminal-Value']!=previous_card:changes+=1
            rows.append({'model':model,'repeat':repeat,'budget':worlds,'seed':stream_seed,'candidates':candidates,'chosen':chosen,
                'top_two_difference':reward_pair(cards,samples,top['card'],nextbest['card'],family),
                'selection_seconds':perf_counter()-started,'prefix_derived_games':len(cards)*worlds,
                'incremental_derived_games':len(cards)*(worlds-previous),'card_changes_so_far':changes})
            previous=worlds;previous_card=chosen['Terminal-Value']
        maximum=rows[-1]['chosen']['Terminal-Value']
        for row in rows:
            if row['repeat']==repeat:row['matches_max_budget']=row['chosen']['Terminal-Value']==maximum
    return rows


def analyze_reliability(obs,c,pid,check=lambda:None,progress=lambda:None):
    started=perf_counter();cards=tuple(sorted(obs.legal_actions));family=c.max_positions*len(c.models)*c.repeats*len(c.budgets)*(17+272)
    rows=[];selection_seed=derived_seed(c.policy_seed,'reliability-selection:'+pid)
    # The model is deliberately absent from the world seed; policy streams still include model/version.
    for model in c.models:rows.extend(nested_selection(obs,cards,c.budgets,model,c.repeats,selection_seed,family,c.safety_tolerance,check,progress))
    selection_seconds=perf_counter()-started;eval_started=perf_counter();evaluations={};raw={}
    eval_seed=derived_seed(1000000+c.validation_offset,'reliability-evaluation:'+pid)
    eval_family=c.max_positions*len(c.models)*17*17
    for model in c.models:
        templates=[create_strategy(model) for _ in range(3)];samples=[[] for _ in cards]
        for trial in range(c.evaluation_worlds):
            check()
            for i,value in enumerate(rollout_trial(obs,cards,templates,eval_seed,trial,check,policy_names=(model,)*3,outcome_hook=extra_outcome)):samples[i].append(value)
            progress()
        table=candidate_table(obs,cards,samples,eval_family);reference=min(table,key=lambda r:(-r['reward'],r['card']['rank'],r['card']['suit']))
        evaluations[model]={'model':model,'seed':eval_seed,'worlds':c.evaluation_worlds,'candidates':table,'reference_card':reference['card'],
            'reference_value':reference['reward'],'regret_method':'全合法手の同じ独立評価から有限標本の参照札を選ぶ探索的Regret。参照選択と測定は未分離。'}
        raw[model]=samples
    for row in rows:
        row['evaluations']=[]
        selection_value=next(x['reward'] for x in row['candidates'] if x['card']==row['chosen']['Terminal-Value'])
        maximum=next(x['chosen']['Terminal-Value'] for x in rows if x['model']==row['model'] and x['repeat']==row['repeat'] and x['budget']==max(c.budgets))
        for model in c.models:
            evaluation=evaluations[model];values={r:next(x for x in evaluation['candidates'] if x['card']==row['chosen'][r]) for r in RULES}
            row['evaluations'].append({'model':model,'in_model':model==row['model'],'rules':[{'rule':r,'card':row['chosen'][r],
                'value':values[r]['reward'],'reward_evidence':values[r]['reward_evidence'],
                'estimated_regret':evaluation['reference_value']-values[r]['reward']} for r in RULES],
                'selection_optimism':selection_value-values['Terminal-Value']['reward'] if model==row['model'] else None,
                'terminal_minus_self':reward_pair(cards,raw[model],row['chosen']['Terminal-Value'],row['chosen']['Self-Middle'],eval_family),
                'terminal_minus_max_budget':reward_pair(cards,raw[model],row['chosen']['Terminal-Value'],maximum,eval_family)})
    frequencies=[]
    for model in c.models:
        for budget in c.budgets:
            group=[r for r in rows if r['model']==model and r['budget']==budget]
            frequencies.append({'model':model,'budget':budget,**distribution(cards,[r['chosen']['Terminal-Value'] for r in group]),
                'candidate_estimate_sd':[{'card':asdict(card),'sd':float(np.std([next(x['reward'] for x in r['candidates'] if x['card']==asdict(card)) for r in group],ddof=1)) if len(group)>1 else None} for card in cards]})
    sensitivity=[]
    for budget in c.budgets:
        for repeat in range(c.repeats):
            group=[r for r in rows if r['budget']==budget and r['repeat']==repeat];chosen=[r['chosen']['Terminal-Value'] for r in group]
            for a in group:
                for b in group:
                    if a['model']==b['model']:continue
                    ca,cb=a['chosen']['Terminal-Value'],b['chosen']['Terminal-Value']
                    inside=reward_pair(cards,raw[a['model']],ca,cb,eval_family);outside=reward_pair(cards,raw[b['model']],ca,cb,eval_family)
                    sensitivity.append({'budget':budget,'repeat':repeat,'selection_model':a['model'],'other_model':b['model'],
                        'same_card':ca==cb,'stable_across_models':all(x==chosen[0] for x in chosen),
                        'in_model_advantage':inside,'out_model_advantage':outside,
                        'point_model_reversal':inside['mean']>0 and outside['mean']<0})
    return {'rows':rows,'frequencies':frequencies,'evaluation_tables':evaluations,'model_sensitivity':sensitivity,
        'legal_count':len(cards),'remaining_rounds':5-obs.turn//3,
        'selection_seconds':selection_seconds,'evaluation_seconds':perf_counter()-eval_started,'elapsed_seconds':perf_counter()-started,
        'selection_derived_games':len(cards)*max(c.budgets)*c.repeats*len(c.models),
        'evaluation_derived_games':len(cards)*c.evaluation_worlds*len(c.models),
        'scope':'最大予算札も有限標本の参照札も真の最適手ではない。評価データは選択反復間で共有し、反復数を独立評価世界数に掛けない。'}


def reliability_summary(positions):
    buckets=defaultdict(lambda:defaultdict(list))
    for p in positions:
        result=p['reliability'];base=['all',p['stratum']['class'],p['period'],f'legal:{result["legal_count"]}',f'rounds:{result["remaining_rounds"]}']
        if p['stratum']['strict_middle']:base.append(p['stratum']['relation']);base.extend(k for k in ('both_small','both_large') if p['stratum'][k])
        for row in result['rows']:
            maximum=max(x['immediate_middle'] for x in row['candidates']);gap=row['top_two_difference']['mean']
            labels=base+[f'immediate-bin:{min(3,int(maximum*4))}',f'top-gap:{"small" if gap<.1 else "medium" if gap<.5 else "large"}',
                'self-terminal:'+('agree' if row['chosen']['Self-Middle']==row['chosen']['Terminal-Value'] else 'disagree')]
            for e in row['evaluations']:
                terminal=next(r for r in e['rules'] if r['rule']=='Terminal-Value')
                values={'reward':terminal['value'],'terminal_minus_self':e['terminal_minus_self']['mean'],
                    'terminal_minus_max_budget':e['terminal_minus_max_budget']['mean'],'estimated_regret':terminal['estimated_regret'],
                    'selection_optimism':e['selection_optimism'],'matches_max_budget':int(row['matches_max_budget']),
                    'selection_seconds':row['selection_seconds']}
                for label in labels:buckets[(p['population'],row['model'],row['budget'],e['model'],label)][p['deal_hash']].append((p['position_hash'],values))
    output=[]
    for (population,selection,budget,evaluation,label),deals in buckets.items():
        means={};differences=[]
        for metric in next(iter(deals.values()))[0][1]:
            per_deal=[]
            for entries in deals.values():
                per_position=defaultdict(list)
                for pid,values in entries:
                    if values[metric] is not None:per_position[pid].append(values[metric])
                if per_position:per_deal.append(float(np.mean([np.mean(rs) for rs in per_position.values()])))
            means[metric]=float(np.mean(per_deal)) if per_deal else None
            if metric=='terminal_minus_self':differences=per_deal
        output.append({'population':population,'selection_model':selection,'budget':budget,'evaluation_model':evaluation,'stratum':label,
            'independent_deals':len(deals),'positions':len({pid for entries in deals.values() for pid,_ in entries}),**means,
            'deal_evidence':deal_evidence(differences,completed=True,comparisons=10000,bound=4),
            'scope':'同じ条件・集団内で反復→局面→配札の順に平均。選抜済み局面の探索的記述。モデルや診断/新規集団を合算しない。'})
    return output
