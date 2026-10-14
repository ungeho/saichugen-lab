"""同一推定予算での規則選択と独立世界による固定カード評価。"""
from collections import Counter,defaultdict
from dataclasses import asdict
from math import isfinite
import numpy as np
from .stratification_analysis import stratify,StrataDefinition,evaluate_stratified
from .evaluation_statistics import fixed_evidence
from ..game.cards import Card

RULES=('Self-Middle','Gap-Control','Safety-Margin','Terminal-Value')
CONTRASTS=(('Safety-Margin','Self-Middle'),('Gap-Control','Self-Middle'),('Terminal-Value','Self-Middle'),('Safety-Margin','Gap-Control'))


def safety_margin(scores,player):
    s=stratify(scores,player,StrataDefinition())
    return {'strict_middle':s['strict_middle'],'minimum_margin':s['gap_min'] if s['strict_middle'] else None,
        'signed_minimum_margin':s['gap_min'],'margin_balance':abs(s['gap_balance']),
        'upper_gap':s['upper_gap'],'lower_gap':s['lower_gap']}


def enrich_candidate(candidate,player):
    """次境界の分布を使用。非中間のmarginを正の安全余裕に変換しない。"""
    rows=[(tuple(map(int,key.split(','))),count) for key,count in candidate['next_scores_distribution'].items()]
    n=sum(count for _,count in rows);middle=0;total=0;balance=0;gap=0;signed=0;upper=0;lower=0
    for scores,count in rows:
        m=safety_margin(scores,player);others=[scores[i] for i in range(3) if i!=player]
        gap+=count*abs(others[0]-others[1]);signed+=count*m['signed_minimum_margin'];upper+=count*m['upper_gap'];lower+=count*m['lower_gap']
        if m['strict_middle']:
            middle+=count;total+=count*m['minimum_margin'];balance+=count*m['margin_balance']
    return {**candidate,'next_opponent_gap':gap/n,'minimum_margin_if_middle':total/middle if middle else None,
        'margin_balance_if_middle':balance/middle if middle else None,'signed_minimum_margin_mean':signed/n,
        'next_upper_gap_mean':upper/n,'next_lower_gap_mean':lower/n,'middle_worlds':middle}


def choose_rules(candidates,tolerance=0):
    if not candidates or not isfinite(tolerance) or not 0<=tolerance<=.1:raise ValueError('候補と0〜0.1の許容幅が必要')
    ordered=sorted(candidates,key=lambda c:(c['card']['rank'],c['card']['suit']))
    def best(key,rows=ordered):return max(rows,key=key)['card']
    maximum=max(c['next_strict_middle'] for c in ordered)
    safe=[c for c in ordered if c['next_strict_middle']>=maximum-tolerance]
    return {'Self-Middle':best(lambda c:c['immediate_middle']),
        'Gap-Control':best(lambda c:c['next_opponent_gap']),
        'Safety-Margin':best(lambda c:c['minimum_margin_if_middle'] if c['minimum_margin_if_middle'] is not None else 0,safe),
        'Terminal-Value':best(lambda c:c['reward'])}


def paired_reward(evaluation,left,right):
    if left==right:
        return {'mean':0.,'sd':0.,'interval':[0.,0.],'independent_world_samples':evaluation['candidates'][0]['trials'],
            'method':'同一行動を共通世界で一度だけ評価。差は恒等的に0。','decision':'hold','unit':'条件付き仮想世界'}
    pair=next(p for p in evaluation['pairs'] if p['a']==right and p['b']==left)
    return pair['evidence']['reward_b_minus_a']


def evaluate_rules(obs,c,position_id,check=lambda:None,progress=lambda:None):
    from .runner import derived_seed
    from time import perf_counter
    start=perf_counter()
    selection=evaluate_stratified(obs,tuple(sorted(obs.legal_actions)),c.continuation,c.trials,
        derived_seed(c.policy_seed,'decision-selection:'+position_id),c.max_positions*(17+272*7),check,progress)
    selection['candidates']=[enrich_candidate(row,obs.player) for row in selection['candidates']]
    chosen=choose_rules(selection['candidates'],c.safety_tolerance)
    cards=tuple(sorted({Card(**card) for card in chosen.values()}))
    selection_seconds=perf_counter()-start;start=perf_counter()
    evaluation=evaluate_stratified(obs,cards,c.continuation,c.evaluation_trials,
        derived_seed(1000000+c.validation_offset,'decision-evaluation:'+position_id),c.max_positions*(4+12*7),check,progress)
    evaluation['candidates']=[enrich_candidate(row,obs.player) for row in evaluation['candidates']]
    rules=[{'rule':name,'selected_card':chosen[name],
        'selection':next(row for row in selection['candidates'] if row['card']==chosen[name]),
        'evaluation':next(row for row in evaluation['candidates'] if row['card']==chosen[name])} for name in RULES]
    comparisons=[{'left':left,'right':right,'same_card':chosen[left]==chosen[right],
        'reward_difference':paired_reward(evaluation,chosen[left],chosen[right])} for left,right in CONTRASTS]
    values={r['rule']:r['evaluation'] for r in rules};sm=values['Self-Middle'];gap=values['Gap-Control'];safety=values['Safety-Margin'];terminal=values['Terminal-Value']
    failures=[{'rule':'Self-Middle','observed':sm['immediate_middle']>terminal['immediate_middle'] and terminal['reward']>sm['reward'],
        'description':'独立評価でも直近2位率は高いがTerminal-Valueより報酬が低い（点推定）。'},
        {'rule':'Gap-Control','observed':gap['next_opponent_gap']>sm['next_opponent_gap'] and gap['next_strict_middle']<sm['next_strict_middle'],
        'description':'独立評価で相手差が大きい一方、中間確率が低い（点推定）。'},
        {'rule':'Safety-Margin','observed':safety['next_strict_middle']>sm['next_strict_middle'] and safety['reward']<sm['reward'],
        'description':'独立評価で中間確率は高いがSelf-Middleより報酬が低い（点推定）。カード温存への因果効果は測定していない。'},
        {'rule':'Terminal-Value','observed':any(v['reward']>terminal['reward'] for v in values.values()),
        'description':'選択標本の報酬最大札が独立評価では他規則に劣る（点推定）。'}]
    return selection,{'rules':rules,'evaluation':evaluation,'comparisons':comparisons,'failures':failures,
        'self_terminal_disagree':chosen['Self-Middle']!=chosen['Terminal-Value'],'all_agree':len(cards)==1,
        'agreement_pairs':[{'left':a,'right':b,'same_card':chosen[a]==chosen[b]} for i,a in enumerate(RULES) for b in RULES[i+1:]],
        'unique_selected_cards':len(cards),'initial_safety':safety_margin(obs.game_scores,obs.player),
        'selection_seconds':selection_seconds,'evaluation_seconds':perf_counter()-start,
        'inference':'独立世界で固定札を評価。局面選抜の一般化・戦略全体の優位性・因果機序は未確認。'}


def decision_positions(records,limit,controls):
    """結果を見る前に五つの中間タグを巡回。重なるタグの局面は一度だけ選ぶ。"""
    priority={t:i for i,t in enumerate([12,11,13,14,9,6,3,0,1,2,4,5,7,8,10])}
    selected=[];seen=set();deals=Counter();sources=Counter()
    def pick(labels,cap):
        while len(selected)<cap:
            added=False
            for label in labels:
                if len(selected)>=cap:break
                options=[r for r in records if r['position_hash'] not in seen and
                    ((r['stratum']['strict_middle'] and (r['stratum']['relation']==label or r['stratum'].get(label) is True)) if label in ('balanced','upper_close','lower_close','both_small','both_large') else r['stratum']['class']==label)]
                if not options:continue
                row=min(options,key=lambda r:(deals[r['deal_hash']],sources[r['source']],priority[r['turn']],r['source'],r['player'],r['position_hash']))
                selected.append(row);seen.add(row['position_hash']);deals[row['deal_hash']]+=1;sources[row['source']]+=1;added=True
            if not added:break
    pick(('balanced','upper_close','lower_close','both_small','both_large'),limit-controls)
    pick(('highest','lowest','tie'),min(limit,len(selected)+controls))
    return selected


def decision_summary(positions):
    buckets=defaultdict(lambda:defaultdict(list))
    for p in positions:
        labels=['all',p['stratum']['class'],p['period'],'source:'+p['source']]
        if p['stratum']['strict_middle']:
            labels.append(p['stratum']['relation']);labels.extend(k for k in ('both_small','both_large') if p['stratum'][k])
        for label in labels:buckets[label][p['deal_hash']].append(p)
    output=[]
    for label,deals in buckets.items():
        rows=[p for group in deals.values() for p in group]
        contrasts=[]
        for left,right in CONTRASTS:
            diffs=[float(np.mean([next(r['reward_difference']['mean'] for r in p['decision']['comparisons'] if r['left']==left and r['right']==right) for p in group])) for group in deals.values()]
            contrasts.append({'left':left,'right':right,'evidence':fixed_evidence(diffs,comparisons=4*20,completed=True,bound=4)})
        output.append({'stratum':label,'independent_deals':len(deals),'positions':len(rows),
            'all_agree_fraction':float(np.mean([np.mean([p['decision']['all_agree'] for p in group]) for group in deals.values()])),
            'self_terminal_disagreement_fraction':float(np.mean([np.mean([p['decision']['self_terminal_disagree'] for p in group]) for group in deals.values()])),
            'agreement_pairs':[{'left':a,'right':b,'agreement_fraction':float(np.mean([np.mean([next(x['same_card'] for x in p['decision']['agreement_pairs'] if x['left']==a and x['right']==b) for p in group]) for group in deals.values()]))} for i,a in enumerate(RULES) for b in RULES[i+1:]],
            'comparisons':contrasts,'interpretation':'配札内の選抜局面を平均し配札を等重み。局面選択と世界推定誤差を含む探索的記述で、母集団の効果ではない。'})
    return output
