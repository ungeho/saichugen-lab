from random import Random
import pytest
from fastapi.testclient import TestClient
from strategy_arena.api.app import create_app
from strategy_arena.game.engine import Game
from strategy_arena.game.cards import Card
from strategy_arena.game.observation import Observation
from strategy_arena.strategies.registry import create_strategy,algorithm_catalog
from strategy_arena.strategies.base import decide
from strategy_arena.experiments.arena import ArenaRequest,run_arena
from strategy_arena.experiments.zigzag_analysis import rank_trace,rank_slots,detect_pattern,summarize_traces
from strategy_arena.experiments.zigzag_lab import zigzag_template,zigzag_result
from strategy_arena.strategies.declarative import DefinitionStore
from test_design_lab import setup,wait


@pytest.mark.parametrize('reverse',[False,True])
def test_alternation_structure_round_continuity_and_public_metadata(reverse):
    game=Game(75);strategy=create_strategy('Reverse Zigzag' if reverse else 'Zigzag');rng=Random(99);rng_state=rng.getstate()
    initial=sorted(game.observe(0).hand,reverse=True);played=[]
    for turn in range(15):
        obs=game.observe(0);decision=decide(strategy,obs,rng,True)
        expected=(max if ((turn%2==0)!=reverse) else min)(obs.legal_actions)
        assert decision.card==expected
        assert decision.details.optional_metadata['initial_hand_rank']==initial.index(expected)+1
        assert decision.details.optional_metadata['remaining_hand_rank']==(1 if (turn%2==0)!=reverse else len(obs.hand))
        played.append(decision.card);game.play((decision.card,game.observe(1).hand[0],game.observe(2).hand[0]))
    assert rng.getstate()==rng_state and len(game.observe(0).hand)==2
    assert set(game.observe(0).hand)<=set(initial[7:10])
    assert [initial.index(c)+1 for c in played[:4]]==([17,1,16,2] if reverse else [1,17,2,16])
    assert len(set(played))==15
    with pytest.raises(ValueError):strategy.choose(game.observe(0),rng)


def test_strength_suits_single_legal_and_no_hidden_state():
    hand=(Card(13,0),Card(13,3),Card(1,3))
    obs=Observation(0,hand,(),(0,0,0),(0,0,0),0,(3,3,3))
    assert create_strategy('Zigzag').choose(obs,Random()).card==Card(13,3)
    assert create_strategy('Reverse Zigzag').choose(obs,Random()).card==Card(1,3)
    one=Observation(0,(Card(2,0),),(),(0,0,0),(0,0,0),14,(1,1,1))
    assert create_strategy('Zigzag').choose(one,Random()).card==Card(2,0)
    game=Game(42);hands=[game.observe(p).hand for p in range(3)]
    from strategy_arena.game.cards import deal
    alternate=Game.from_deal((hands[0],hands[2],hands[1]),deal(42)[1])
    assert game.observe(0)==alternate.observe(0)
    assert create_strategy('Zigzag').choose(game.observe(0),Random(1))==create_strategy('Zigzag').choose(alternate.observe(0),Random(999))
    assert any(x['name']=='Zigzag' and x['description_available'] for x in algorithm_catalog())


def test_rank_slots_and_trace_scores_reward_ties():
    assert rank_slots((8,3,3),1)==[2,3]
    assert rank_slots((8,8,3),0)==[1,2]
    assert rank_slots((0,0,0),2)==[1,2,3]
    game=Game(42)
    for _ in range(15):game.play(tuple(game.observe(p).hand[0] for p in range(3)))
    trace=rank_trace(42,game.observe(0).history,0)
    assert [t['period'] for t in trace['turns']]==[0]*5+[1]*5+[2]*5
    assert len(trace['rounds'])==5
    for t,e in zip(trace['turns'],game.observe(0).history):
        assert t['turn_middle']==(e.winner==0)
        assert t['turn_rank']==rank_slots(e.cards,0)[0]
    assert sum(r['awarded_score'] for r in trace['rounds'])==game.observe(0).game_scores[0]
    from strategy_arena.game.rewards import terminal_rewards
    assert trace['terminal_reward']==terminal_rewards(game.winners)[0]


def test_public_pattern_detector_is_only_necessary_condition():
    cards=(Card(13,3),Card(1,0),Card(12,3),Card(2,0))
    result=detect_pattern(cards)
    assert result['compatible_patterns']==['Zigzag'] and result['exact_next_card'] is None
    assert result['next_side_if_rule_known']['Zigzag']=='strongest'
    assert len(detect_pattern(())['compatible_patterns'])==2
    assert detect_pattern((Card(5,0),Card(6,0),Card(7,0)))['compatible_patterns']==[]


def test_common_deals_rotation_analysis_and_optional_logging(tmp_path):
    defs=DefinitionStore(tmp_path/'defs.sqlite')
    request=ArenaRequest(participants=['Zigzag','Reverse Zigzag'],deals=2,start_offset=100,capture_rank_trace=True)
    config=request.resolve(defs);rows=[];run_arena(config,rows.append)
    summary=summarize_traces(config,rows)
    assert len(rows)==24 and len(summary)==2
    for s in summary:
        assert s['independent_deals']==2 and s['games']==12
        assert sum(s['sole_ranks'])+s['tie_rate']==pytest.approx(1)
        assert sum(s['rank_patterns'].values())==pytest.approx(1)
        for p in s['periods']:assert sum(p['ranks'])==pytest.approx(1)
        for r in s['rounds']:assert sum(r['round_ranks'])==pytest.approx(1)
        assert s['average_reward']==pytest.approx(sum(d['average_reward'] for d in s['per_deal'])/2)
    config.capture_rank_trace=False;ordinary=[];run_arena(config,ordinary.append)
    assert all('rank_trace' not in row for row in ordinary)
    assert [r['terminal_rewards'] for r in rows]==[r['terminal_rewards'] for r in ordinary]


def test_design_registered_zigzag_completed_and_api(tmp_path):
    design,jobs,arena=setup(tmp_path)
    try:
        data=zigzag_template().model_dump(mode='json');data['evaluation']['deals']=1
        from strategy_arena.experiments.design_lab import PlanSpec
        s=PlanSpec.model_validate(data);design.draft(s);registered=design.register(s.plan_id,1)
        assert registered['registered']['estimate']['games']==72
        assert len(registered['registered']['family'])==15
        design.start(s.plan_id,1,registered['plan_hash']);assert wait(design,s.plan_id)['state']=='Completed'
        result=zigzag_result(design,s.plan_id,1)
        assert len(result['summaries'])==2
        assert all(len(x['strategies'])==6 for x in result['summaries'])
    finally:design.close();jobs.close();arena.close()
    with TestClient(create_app(tmp_path/'api.sqlite')) as client:
        s=client.post('/api/zigzag/template',json={}).json()
        assert s['evaluation']['capture_rank_trace'] and s['evaluation']['seed_partition']=='development'
        draft=client.post('/api/design/plans',json=s).json()
        assert client.get(f"/api/zigzag/plans/{draft['id']}/1").json()['summaries']==[]
        assert client.get('/api/zigzag/plans').json()==[{'id':draft['id'],'version':1}]
