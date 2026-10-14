"""観測のみの行動介入比較。局面探索と独立な世界標本の検証を分ける。"""
from dataclasses import asdict
from itertools import combinations
from random import Random
from collections import Counter
import numpy as np
from .evolution import digest
from .runner import derived_seed
from .evaluation_statistics import fixed_evidence as _fixed_evidence
from .zigzag_analysis import rank_slots
from ..rollouts import rollout_trial
from ..game.rules import median_players
from ..strategies.registry import create_strategy

LIGHT=('Random','Greedy','Conservative','ScoreAware','Heuristic','Zigzag','Reverse Zigzag')

def fixed_evidence(*args,**kwargs):
    result=_fixed_evidence(*args,**kwargs)
    result['independent_world_samples']=result.pop('independent_deals')
    result['reason']=result['reason'].replace('独立配札','独立仮想世界')
    result['unit']='同一公開局面に条件付けた独立仮想世界。実配札数ではない。'
    return result


def presentation(value):
    """旧局面ログの単位表現を読取時だけ補正。元のSQLite実験は変更しない。"""
    if isinstance(value,list):return [presentation(v) for v in value]
    if not isinstance(value,dict):return value
    out={k:presentation(v) for k,v in value.items()}
    if 'independent_deals' in out and 'adjusted_alpha' in out:
        out['independent_world_samples']=out.pop('independent_deals')
        out['reason']=out.get('reason','').replace('独立配札','独立仮想世界')
        out['unit']='同一公開局面に条件付けた独立仮想世界。実配札数ではない。'
    if 'immediate_a_minus_b' in out and 'reward_b_minus_a' in out:
        a=out['immediate_a_minus_b']['mean'];b=out['reward_b_minus_a']['mean']
        reversal=a is not None and b is not None and a>0 and b>0
        out['status']='point_estimate_candidate' if reversal else 'paired_comparison'
        out['explanation']=f'直近2位率差A−Bは{a:+.3f}、終局報酬差B−Aは{b:+.3f}。この標本での点推定の逆転は'+('あり。' if reversal else 'なし。')+'不確実性を確認し、選択標本と独立な再評価が必要。相手得点差の経路は因果証明ではありません。'
    return out


def outcome_metrics(game,obs):
    history=game.observe(obs.player).history;p=obs.player;op=[i for i in range(3) if i!=p]
    first=history[obs.turn];end=history[(obs.turn//3)*3+2];final=game.observe(p).game_scores
    final_start=history[11].game_scores if obs.turn<12 else None
    return {'immediate_middle':int(first.winner==p),'round_winners':list(median_players(end.round_scores)),
        'round_scores':list(end.round_scores),'final_start_middle':int(p in median_players(final_start)) if final_start is not None else None,
        'final_middle':int(p in game.winners),'opponent_gap_change':abs(final[op[0]]-final[op[1]])-abs(obs.game_scores[op[0]]-obs.game_scores[op[1]]),
        'score_changes':[final[i]-obs.game_scores[i] for i in range(3)],
        'opponent_turn_middle_difference':sum(e.winner==op[0] for e in history[obs.turn:])/len(history[obs.turn:])-sum(e.winner==op[1] for e in history[obs.turn:])/len(history[obs.turn:])}


def evaluate_position(obs,cards,names,trials,seed,check=lambda:None,progress=lambda:None, comparisons=None):
    if not cards or len(set(cards))!=len(cards) or any(c not in obs.legal_actions for c in cards):raise ValueError('候補は重複しない合法手')
    templates=[create_strategy(n) for n in names];samples=[[] for _ in cards]
    for trial in range(trials):
        for i,row in enumerate(rollout_trial(obs,cards,templates,seed,trial,check,policy_names=names,outcome_hook=outcome_metrics)):samples[i].append(row)
        progress()
    candidates=[]
    family=comparisons or max(1,len(cards)*(len(cards)-1)//2*3)
    for card,rows in zip(cards,samples):
        candidates.append({'card':asdict(card),'trials':trials,'immediate_middle':float(np.mean([r['immediate_middle'] for r in rows])),
            'reward':float(np.mean([r['reward'] for r in rows])),'reward_evidence':fixed_evidence([r['reward'] for r in rows],comparisons=family,completed=True,bound=2),
            'sole_win_rate':float(np.mean([r['sole_win'] for r in rows])),'win_rate':float(np.mean([r['win'] for r in rows])),
            'round_result_distribution':dict(Counter(','.join(map(str,r['round_winners'])) for r in rows)),
            'final_start_middle':float(np.mean([r['final_start_middle'] for r in rows])) if obs.turn<12 else None,
            'opponent_gap_change':float(np.mean([r['opponent_gap_change'] for r in rows])),
            'score_changes':np.mean([r['score_changes'] for r in rows],axis=0).tolist(),
            'opponent_turn_middle_difference':float(np.mean([r['opponent_turn_middle_difference'] for r in rows]))})
    pairs=[]
    for a,b in combinations(range(len(cards)),2):
        for high,low in [(a,b),(b,a)]:
            if candidates[high]['immediate_middle']>candidates[low]['immediate_middle'] and candidates[low]['reward']>candidates[high]['reward']:
                pairs.append(pair_evidence(candidates,samples,high,low,family))
    return presentation({'candidates':candidates,'paired':[pair_evidence(candidates,samples,a,b,family) for a,b in combinations(range(len(cards)),2)],'reversals':pairs,'family_size':family,'sample_unit':'同一公開局面に条件付けた独立サンプリング世界。実配札数ではない。','sampler':'uniform-unseen-v1;行動尤度による重み付けなし','continuation':list(names),'seed':seed,
        'limitations':'候補間は共通世界・方策乱数。進行分岐後の乱数消費は異なり得る。区間は固定標本診断で逐次判定ではない。'})


def pair_evidence(candidates,samples,high,low,family):
    left,right=samples[high],samples[low]
    immediate=[a['immediate_middle']-b['immediate_middle'] for a,b in zip(left,right)]
    rewards=[b['reward']-a['reward'] for a,b in zip(left,right)]
    gaps=[b['opponent_gap_change']-a['opponent_gap_change'] for a,b in zip(left,right)]
    return {'a':candidates[high]['card'],'b':candidates[low]['card'],
        'immediate_a_minus_b':fixed_evidence(immediate,comparisons=family,completed=True,bound=1),
        'reward_b_minus_a':fixed_evidence(rewards,comparisons=family,completed=True,bound=4),
        'gap_b_minus_a':fixed_evidence(gaps,comparisons=family,completed=True,bound=390),
        'status':'point_estimate_candidate','explanation':f"Aの直近2位率は{candidates[high]['immediate_middle']:.3f}、Bは{candidates[low]['immediate_middle']:.3f}。終局報酬はA {candidates[high]['reward']:+.3f}、B {candidates[low]['reward']:+.3f}。点推定の逆転候補で、独立標本による再評価が必要。相手得点差の経路は因果証明ではありません。"}


def classify(obs,result):
    p=obs.player;scores=obs.game_scores;op=[i for i in range(3) if i!=p];ranks=rank_slots(scores,p)
    best=max(result['candidates'],key=lambda c:c['reward'])['card'];labels=[]
    labels.append('同点' if len(ranks)>1 else {1:'最高得点',2:'中間得点',3:'最低得点'}[ranks[0]])
    labels.append('相手差小(<5)' if abs(scores[op[0]]-scores[op[1]])<5 else '相手差大(>=5)')
    labels.append('序盤' if obs.turn<5 else '中盤' if obs.turn<10 else '終盤')
    for name in ('Zigzag','ScoreAware'):
        card=create_strategy(name).choose(obs,Random(derived_seed(42,name))).card
        if asdict(card)!=best:labels.append(name+'と報酬最大候補が異なる')
    return labels
