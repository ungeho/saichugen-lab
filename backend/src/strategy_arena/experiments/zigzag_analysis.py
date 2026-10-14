"""順位解析は実験用の後処理。対戦中のStrategyへ完全情報を渡さない。"""
from dataclasses import asdict
from itertools import combinations
import numpy as np
from .quality_statistics import complete_deals
from .arena import ArenaPlan
from ..game.cards import deal,Card
from ..game.rules import median_players
from ..game.rewards import terminal_rewards

PERIODS=('序盤1–5手','中盤6–10手','終盤11–15手')

def rank_slots(values,player):
    higher=sum(x>values[player] for x in values);equal=sum(x==values[player] for x in values)
    return list(range(higher+1,higher+equal+1))


def detect_pattern(cards):
    """公開列が両端交互と矛盾するかだけ調べる。尤度や確率ではない。"""
    def compatible(reverse):
        return all(all((later<card if (i%2==0)!=reverse else later>card) for later in cards[i+1:]) for i,card in enumerate(cards))
    possible=[name for rev,name in [(False,'Zigzag'),(True,'Reverse Zigzag')] if compatible(rev)]
    return {'public_actions':len(cards),'compatible_patterns':possible,'next_side_if_rule_known':{name:('strongest' if (len(cards)%2==0)!=(name=='Reverse Zigzag') else 'weakest') for name in possible},
        'exact_next_card':None,'conclusion':'公開列との必要条件だけ。使っている確率や実際の次札を特定しません。'}


def rank_trace(seed,history,player):
    initial=sorted(deal(seed)[0][player],reverse=True);remaining=list(initial);turns=[];rounds=[];previous=(0,0,0)
    for event in history:
        card=event.cards[player];ordered=sorted(remaining,reverse=True);turn_rank=rank_slots(event.cards,player)[0]
        turns.append({'action':event.index+1,'round':event.index//3+1,'round_turn':event.index%3+1,'period':event.index//5,
            'card':asdict(card),'initial_rank':initial.index(card)+1,'remaining_rank':ordered.index(card)+1,'remaining_count':len(remaining),
            'turn_rank':turn_rank,'turn_middle':turn_rank==2,'round_scores':event.round_scores,'game_scores':event.game_scores,
            'remaining_initial_ranks':[initial.index(c)+1 for c in ordered if c!=card]})
        remaining.remove(card)
        if event.index%3==2:
            scores=event.game_scores;others=[scores[p] for p in range(3) if p!=player]
            rounds.append({'round':event.index//3+1,'round_score':event.round_scores[player],'round_rank_slots':rank_slots(event.round_scores,player),
                'round_middle':player in median_players(event.round_scores),'awarded_score':scores[player]-previous[player],
                'cumulative_score':scores[player],'cumulative_rank_slots':rank_slots(scores,player),
                'gap_to_top':max(scores)-scores[player],'gap_to_bottom':scores[player]-min(scores),
                'strict_middle':min(others)<scores[player]<max(others),'inclusive_middle':min(others)<=scores[player]<=max(others)})
            previous=scores
    scores=history[-1].game_scores;slots=rank_slots(scores,player);winners=median_players(scores)
    return {'turns':turns,'rounds':rounds,'final_rank_slots':slots,'final_tied':len(slots)>1,'final_score':scores[player],
        'terminal_reward':terminal_rewards(winners)[player],'won':player in winners,'sole_win':winners==(player,),
        'public_pattern':detect_pattern(tuple(e.cards[player] for e in history)),
        'scope':'研究用の本人の初期順位。相手の非公開手札は記録しない。'}


def summarize_traces(config,rows):
    result=[]
    for setting in config.settings:
        groups=complete_deals(config,rows,setting);valid=[r for group in groups.values() for r in group]
        if not valid or any('rank_trace' not in r for r in valid):continue
        # 全6役割順を配札内で平均してから配札を等重みで平均する。
        per_deal=[]
        for deal_id,group in groups.items():
            traces=[r['rank_trace'] for r in group];periods=[];rounds=[]
            for p in range(3):
                ts=[t for tr in traces for t in tr['turns'] if t['period']==p]
                periods.append({'period':PERIODS[p],'ranks':[sum(t['turn_rank']==rank for t in ts)/len(ts) for rank in (1,2,3)],
                    'mean_initial_rank':float(np.mean([t['initial_rank'] for t in ts]))})
            for i in range(5):
                rs=[tr['rounds'][i] for tr in traces]
                rounds.append({'round':i+1,**{k:float(np.mean([r[k] for r in rs])) for k in ('round_score','awarded_score','cumulative_score','gap_to_top','gap_to_bottom','round_middle','strict_middle','inclusive_middle')},
                    'round_ranks':[sum((1/len(r['round_rank_slots'])) if rank in r['round_rank_slots'] else 0 for r in rs)/6 for rank in (1,2,3)],
                    'cumulative_ranks':[sum((1/len(r['cumulative_rank_slots'])) if rank in r['cumulative_rank_slots'] else 0 for r in rs)/6 for rank in (1,2,3)]})
            per_deal.append({'deal_id':deal_id,'periods':periods,'rounds':rounds,'average_reward':float(np.mean([t['terminal_reward'] for t in traces])),
                'sole_ranks':[sum(t['final_rank_slots']==[rank] for t in traces)/6 for rank in (1,2,3)],
                'rank_patterns':{pattern:sum(','.join(map(str,t['final_rank_slots']))==pattern for t in traces)/6 for pattern in ('1','2','3','1,2','2,3','1,2,3')},
                'tie_rate':sum(t['final_tied'] for t in traces)/6,'win_rate':sum(t['won'] for t in traces)/6})
        result.append({'strategy':setting.reference,'independent_deals':len(groups),'games':len(valid),'per_deal':per_deal,
            'periods':[{'period':PERIODS[p],'ranks':np.mean([d['periods'][p]['ranks'] for d in per_deal],axis=0).tolist()} for p in range(3)],
            'rounds':[{'round':i+1,**{k:np.mean([d['rounds'][i][k] for d in per_deal],axis=0).tolist() for k in per_deal[0]['rounds'][i] if k!='round'}} for i in range(5)],
            'average_reward':float(np.mean([d['average_reward'] for d in per_deal])),
            'sole_ranks':np.mean([d['sole_ranks'] for d in per_deal],axis=0).tolist(),'tie_rate':float(np.mean([d['tie_rate'] for d in per_deal])),
            'rank_patterns':{k:float(np.mean([d['rank_patterns'][k] for d in per_deal])) for k in per_deal[0]['rank_patterns']},
            'example':valid[0]['rank_trace']})
    return result
