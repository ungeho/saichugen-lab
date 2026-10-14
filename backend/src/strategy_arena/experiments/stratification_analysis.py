"""版付き層別と条件付き世界比較。既存サンプラー・報酬・区間を再利用。"""
from dataclasses import asdict
from itertools import combinations
from collections import Counter,defaultdict
import numpy as np
from time import perf_counter
from pydantic import Field,model_validator
from .design_lab import StrictModel
from .middle_analysis import fixed_evidence,outcome_metrics
from ..rollouts import rollout_trial
from ..strategies.registry import create_strategy

class StrataDefinition(StrictModel):
    version:str=Field(default='strict-middle-v1',pattern=r'^strict-middle-v1$')
    small:int=Field(default=5,strict=True,ge=1,le=20)
    large:int=Field(default=10,strict=True,ge=2,le=40)
    balance_tolerance:int=Field(default=0,strict=True,ge=0,le=10)
    @model_validator(mode='after')
    def valid(self):
        if self.large<=self.small:raise ValueError('大差閾値は小差閾値より大きく')
        return self


def stratify(scores,p,definition):
    others=[scores[i] for i in range(3) if i!=p];s=scores[p];upper=max(others)-s;lower=s-min(others)
    strict=upper>0 and lower>0
    group='strict_middle' if strict else 'tie' if len(set(scores))<3 else 'highest' if s>max(others) else 'lowest'
    relation='balanced' if abs(upper-lower)<=definition.balance_tolerance else 'upper_close' if upper<lower else 'lower_close'
    return {'class':group,'strict_middle':strict,'upper_gap':upper,'lower_gap':lower,'gap_balance':upper-lower,'gap_min':min(upper,lower),'gap_total':upper+lower,
        'relation':relation if strict else None,'equal_gaps':strict and upper==lower,'both_small':strict and max(upper,lower)<=definition.small,'both_large':strict and min(upper,lower)>=definition.large,
        'definition':definition.model_dump()}


def period(turn):
    return 'early' if turn<5 else 'middle' if turn<11 else 'before_final_round' if turn==11 else 'final_round_start' if turn==12 else 'final_round'


def extra_outcome(game,obs):
    r=outcome_metrics(game,obs);history=game.observe(obs.player).history;p=obs.player;end=history[obs.turn//3*3+2];scores=end.game_scores;final=game.observe(p).game_scores
    def strict(vals):
        o=[vals[i] for i in range(3) if i!=p]
        return int(min(o)<vals[p]<max(o))
    o=[i for i in range(3) if i!=p];upper=max(obs.game_scores[i] for i in o)-obs.game_scores[p];lower=obs.game_scores[p]-min(obs.game_scores[i] for i in o)
    return {**r,'immediate_probabilities':[int(history[obs.turn].winner==i) for i in range(3)],'round_score':end.round_scores[p],
        'next_scores':list(scores),'next_strict_middle':strict(scores),'final_strict_middle':strict(final),
        'final_start_strict_middle':strict(history[11].game_scores) if obs.turn<12 else None,
        'upper_gap_change':max(final[i] for i in o)-final[p]-upper,'lower_gap_change':final[p]-min(final[i] for i in o)-lower}


def evaluate_stratified(obs,cards,names,trials,seed,family,check=lambda:None,progress=lambda:None):
    templates=[create_strategy(n) for n in names];samples=[[] for _ in cards];timings=[0.]*len(cards)
    if len(set(cards))!=len(cards) or not cards or any(c not in obs.legal_actions for c in cards):raise ValueError('重複しない合法手が必要')
    from .runner import derived_seed
    for t in range(trials):
        current=[0,0.]
        def timing(stage):
            if stage=='started':current[1]=perf_counter()
            else:timings[current[0]]+=perf_counter()-current[1];current[0]+=1
        for i,r in enumerate(rollout_trial(obs,cards,templates,seed,t,check,policy_names=names,outcome_hook=extra_outcome,on_game=timing)):samples[i].append(r)
        progress()
    candidates=[]
    for card,rs in zip(cards,samples):
        means={k:float(np.mean([r[k] for r in rs])) for k in ('immediate_middle','reward','sole_win','win','round_score','next_strict_middle','final_strict_middle','upper_gap_change','lower_gap_change','opponent_gap_change')}
        candidates.append({'card':asdict(card),'trials':trials,'rollout_seconds':timings[len(candidates)],**means,'immediate_probabilities':np.mean([r['immediate_probabilities'] for r in rs],axis=0).tolist(),
            'next_scores_distribution':dict(Counter(','.join(map(str,r['next_scores'])) for r in rs)),
            'next_scores_mean':np.mean([r['next_scores'] for r in rs],axis=0).tolist(),
            'final_start_strict_middle':float(np.mean([r['final_start_strict_middle'] for r in rs])) if obs.turn<12 else None,
            'reward_evidence':fixed_evidence([r['reward'] for r in rs],comparisons=family,completed=True,bound=2)})
    pairs=[]
    for x,y in combinations(range(len(cards)),2):
        for a,b in ((x,y),(y,x)):
            ca,cb=candidates[a],candidates[b]
            rs=list(zip(samples[a],samples[b]));op=[i for i in range(3) if i!=obs.player]
            evidence={key:fixed_evidence(values,comparisons=family,completed=True,bound=bound) for key,values,bound in [
                ('immediate_a_minus_b',[l['immediate_middle']-r['immediate_middle'] for l,r in rs],1),
                ('reward_b_minus_a',[r['reward']-l['reward'] for l,r in rs],4),
                ('gap_b_minus_a',[r['opponent_gap_change']-l['opponent_gap_change'] for l,r in rs],390),
                ('gap_b_from_initial',[r['opponent_gap_change'] for l,r in rs],195),
                ('maintenance_b_minus_a',[r['next_strict_middle']-l['next_strict_middle'] for l,r in rs],1),
                ('opponent_a_b_minus_a',[r['immediate_probabilities'][op[0]]-l['immediate_probabilities'][op[0]] for l,r in rs],1),
                ('opponent_b_b_minus_a',[r['immediate_probabilities'][op[1]]-l['immediate_probabilities'][op[1]] for l,r in rs],1)]}
            flags=case_flags(ca,cb,initial_strict=stratify(obs.game_scores,obs.player,StrataDefinition())['strict_middle'])
            pairs.append({'a':ca['card'],'b':cb['card'],'g':flags,'case_b':all(flags.values()),'evidence':evidence,
                'uncertainty_small':all(evidence[k]['interval'] and evidence[k]['interval'][0]>0 for k in ('immediate_a_minus_b','reward_b_minus_a','gap_b_minus_a','gap_b_from_initial','maintenance_b_minus_a')),
                'status':'point_estimate_candidate' if flags['G1'] else 'paired_comparison','causal_mechanism_supported':False})
    return {'candidates':candidates,'pairs':pairs,'reversals':[p for p in pairs if p['g']['G1']],'case_b_candidates':[p for p in pairs if p['case_b']],
        'family_size':family,'continuation':list(names),'seed':seed,'sampler':'uniform-unseen-v1','sample_unit':'同一公開局面条件付き仮想世界。独立配札ではない。'}


def case_flags(a,b,initial_strict=True):
    return {'G1':a['immediate_middle']>b['immediate_middle'] and b['reward']>a['reward'],
        'G2':b['opponent_gap_change']>0 and b['opponent_gap_change']>a['opponent_gap_change'],
        'G3':initial_strict and b['next_strict_middle']>a['next_strict_middle'],
        'G4':b['reward']>a['reward']}


def select_positions(records,limit,controls,turns):
    priority={t:i for i,t in enumerate([12,11,13,14,9,6,3,0,1,2,4,5,7,8,10])};chosen=[];used_deals=Counter();used_sources=Counter()
    def pick(categories,cap):
        groups={k:[r for r in records if r['stratum']['class']=='strict_middle' and r['stratum']['relation']==k] if k in ('balanced','upper_close','lower_close') else [r for r in records if r['stratum']['class']==k] for k in categories}
        while any(groups.values()) and len(chosen)<cap:
            for k in categories:
                if len(chosen)>=cap:break
                if not groups[k]:continue
                r=min(groups[k],key=lambda r:(used_deals[r['deal_hash']],used_sources[r['source']],priority[r['turn']],r['source'],r['player'],r['position_hash']))
                groups[k].remove(r);chosen.append(r);used_deals[r['deal_hash']]+=1;used_sources[r['source']]+=1
    pick(('balanced','upper_close','lower_close'),limit-controls)
    pick(('highest','lowest','tie'),limit)
    return chosen


def cluster_summary(positions):
    # 推定の強さではなく、配札内局面割合を等重みで要約する。
    buckets=defaultdict(lambda:defaultdict(list))
    for p in positions:
        labels=[p['stratum']['relation'] if p['stratum']['strict_middle'] else p['stratum']['class']]
        labels += [k for k in ('both_small','both_large') if p['stratum'].get(k)]
        for label in labels:
            buckets[label][p['deal_hash']].append(p)
    return [{'stratum':label,'independent_deals':len(deals),'positions':sum(map(len,deals.values())),
        'deal_mean_reversal_fraction':float(np.mean([np.mean([bool(p['search']['reversals']) for p in rows]) for rows in deals.values()])),
        'deal_mean_case_b_fraction':float(np.mean([np.mean([bool(p['search']['case_b_candidates']) for p in rows]) for rows in deals.values()])),
        'interpretation':'同一配札内で局面を平均し配札を等重み。探索的な選抜済み局面割合で、母集団の有効性推定ではない。'} for label,deals in buckets.items()]
