from copy import deepcopy
from dataclasses import asdict,replace
from random import Random
import json

import pytest
from fastapi.testclient import TestClient

from strategy_arena.strategies.declarative import StrategyDefinition,DeclarativeStrategy,DefinitionStore,builtin_definitions,resolved_theories,score_position
from strategy_arena.experiments.arena import ArenaRequest,ArenaPlan,arena_jobs,arena_estimate,run_arena,compare_arena
from strategy_arena.experiments.storage import ExperimentStore
from strategy_arena.game.engine import Game
from strategy_arena.game.rewards import terminal_rewards
from strategy_arena.rollouts import sampled_game
from strategy_arena.api.app import create_app
from test_rollout_quality import wait
import strategy_arena.experiments.arena as module


def raw():
    data=builtin_definitions()[0].model_dump(mode='json');data.pop('definition_hash');return data


def test_five_distinct_definitions_hash_round_trip_and_legal_reproducible_actions():
    definitions=builtin_definitions();assert len(definitions)==5
    assert len({json.dumps(d.theory_config.model_dump(),sort_keys=True) for d in definitions})==5
    obs=Game(4).observe(0)
    for d in definitions:
        assert StrategyDefinition.model_validate_json(d.model_dump_json()).definition_hash==d.definition_hash
        reordered=json.loads(json.dumps(d.model_dump(mode='json'),sort_keys=True));assert StrategyDefinition.model_validate(reordered).definition_hash==d.definition_hash
        strategy=DeclarativeStrategy(d);before=strategy.parameters
        a=strategy.choose_detailed(obs,Random(4));b=strategy.choose_detailed(obs,Random(4))
        assert a.card in obs.legal_actions and a.card==b.card
        assert a.details.optional_metadata['declarative']['definition_hash']==d.definition_hash
        assert a.details.candidates==b.details.candidates and strategy.parameters==before


@pytest.mark.parametrize('change',[
 {'python':'print(1)'},{'shell':'cmd.exe'},{'file':'C:/secret'},{'evaluation_seed':42},
 {'selection':'eval'},{'schema_version':2},{'definition_hash':'0'*64},
 {'total_budget':5}, {'selection':'theory_search','total_budget':257},
 {'theory_config':{'theories':[{'id':'unknown'}]}},
 {'theory_config':{'theories':[{'id':'public_memory','weight':3}]}},
 {'rules':[{'phase':'python','weights':{'round_focus':1},'explanation':'bad'}]},
 {'rules':[{'weights':{'not_defined':1},'explanation':'bad'}]},
 {'rules':[{'weights':{'round_focus':True},'explanation':'bad'}]},
 {'seed_mode':'fixed_policy'}, {'version':'latest'}, {'created_at':'2026-10-13T00:00:00'},
])
def test_untrusted_definition_rejected(change):
    with pytest.raises(ValueError):StrategyDefinition.model_validate({**raw(),**change})


def test_conditions_first_match_are_public_and_deterministic():
    d=next(d for d in builtin_definitions() if d.id=='codex_adaptive_theorist');obs=Game(3).observe(0)
    early,index=resolved_theories(d,obs);assert index==1
    high,index=resolved_theories(d,replace(obs,game_scores=(30,10,20)));assert index==0
    late,index=resolved_theories(d,replace(obs,turn=12,game_scores=(10,20,30)));assert index==2
    assert early.model_dump()!=late.model_dump()!=high.model_dump()
    assert score_position(replace(obs,game_scores=(10,10,30)))=='tied'
    assert all(s.weight<=2 for s in high.theories)


def test_append_only_parent_hash_and_forward_cycle_rejection(tmp_path):
    store=DefinitionStore(tmp_path/'definitions.sqlite');parent=builtin_definitions()[0]
    child=raw();child.update(id=parent.id,version='1.0.1',parent={'id':parent.id,'version':parent.version,'definition_hash':parent.definition_hash},change_summary='重みを変更',change_reason='仮説の追試')
    child['theory_config']=parent.theory_config.model_dump();child['theory_config']['theories'][0]['weight']=.75
    candidate=StrategyDefinition.model_validate(child);store.add(candidate);store.add(candidate)
    assert store.get(candidate.reference).definition_hash==candidate.definition_hash
    altered=deepcopy(child);altered['description']='同じ版を変更'
    with pytest.raises(ValueError):store.add(StrategyDefinition.model_validate(altered))
    assert store.get(parent.reference).definition_hash==parent.definition_hash
    bad=deepcopy(child);bad['version']='1.0.2';bad['parent']['definition_hash']='0'*64
    with pytest.raises(ValueError):store.add(StrategyDefinition.model_validate(bad))
    bad['parent']={'id':'missing_parent','version':'1.0.0','definition_hash':'0'*64}
    with pytest.raises(ValueError):store.add(StrategyDefinition.model_validate(bad))
    bad['parent']={'id':bad['id'],'version':bad['version'],'definition_hash':'0'*64}
    with pytest.raises(ValueError):StrategyDefinition.model_validate(bad)


def test_no_hidden_hands_or_deal_seeds_in_strategy_input_and_rng_separated(tmp_path,monkeypatch):
    store=DefinitionStore(tmp_path/'d.sqlite');ref=builtin_definitions()[0].reference
    plan=ArenaRequest(participants=[ref],deals=1,opponents=('Random','Random')).resolve(store)
    calls=[];original=module._play_game
    def spy(seed,names,*args,**kwargs):
        calls.append((seed,[r.getstate() for r in kwargs['rngs']]))
        for p in kwargs['strategies']:
            assert not hasattr(p.strategy,'deal_seeds') and not hasattr(p.strategy,'evaluation_seed')
        return original(seed,names,*args,**kwargs)
    monkeypatch.setattr(module,'_play_game',spy)
    a=[];b=[];run_arena(plan,a.append)
    other=plan.model_copy(update={'deal_seeds':[101]});run_arena(other,b.append)
    assert [states for seed,states in calls[:6]]==[states for seed,states in calls[6:]]
    obs=Game(3).observe(0);world1=sampled_game(obs,Random(1));world2=sampled_game(obs,Random(2))
    for d in builtin_definitions():
        s=DeclarativeStrategy(d)
        assert s.choose(world1.observe(0),Random(8)).card==s.choose(world2.observe(0),Random(8)).card
    assert set(asdict(obs))=={'player','hand','history','round_scores','game_scores','turn','hand_sizes'}


def test_arena_reproducibility_rotation_duplicate_seats_storage_and_statistics(tmp_path):
    store=ExperimentStore(tmp_path/'arena.sqlite');definitions=DefinitionStore(store.path)
    refs=[d.reference for d in builtin_definitions()[:3]]
    plan=ArenaRequest(participants=refs,opponents=(refs[0],refs[0]),deals=2).resolve(definitions)
    jobs=arena_jobs(store)
    try:
        a=wait(jobs,jobs.submit(plan)['id']);b=wait(jobs,jobs.submit(plan)['id'])
        assert a['status']==b['status']=='completed'
        clean=lambda p:[{k:v for k,v in r.items() if k not in ('game_elapsed_ns','decisions','role_records')} for r in p['results']]
        assert clean(a)==clean(b) and len(a['results'])==36
        assert all(tuple(r['terminal_rewards'])==terminal_rewards(r['winners']) for r in a['results'])
        assert all(s['independent_deals']==2 and s['games']==12 and s['reward_ci95'] is None for s in a['summary']['settings'])
        assert all(sum(t['games'] for t in s['seats'])==12 for s in a['summary']['settings'])
        assert all(abs(s['loss_rate']+s['sole_win_rate']+s['joint_win_rate']-1)<1e-10 for s in a['summary']['settings'])
        assert json.loads(json.dumps(store.get(a['id'])))==store.get(a['id'])
        comparison=compare_arena(a,b,plan.settings[0].identifier,plan.settings[1].identifier)
        assert comparison['comparable'] and comparison['independent_deals']==2
        changed=deepcopy(b);changed['config']['policy_seed']=99
        assert not compare_arena(a,changed,plan.settings[0].identifier,plan.settings[1].identifier)['comparable']
        changed=deepcopy(b);changed['config']['deal_seeds']=[101,102]
        assert not compare_arena(a,changed,plan.settings[0].identifier,plan.settings[1].identifier)['comparable']
    finally:jobs.close()


def test_search_budget_protection_and_fixed_policy_seed(tmp_path):
    definitions=DefinitionStore(tmp_path/'d.sqlite')
    with pytest.raises(ValueError):ArenaRequest(participants=['monte_carlo_rollout']).resolve(definitions)
    plan=ArenaRequest(participants=['monte_carlo_rollout'],include_expensive=True,deals=1).resolve(definitions)
    assert arena_estimate(plan)['rollout_upper_bound']==7240
    data=raw();data.update(seed_mode='fixed_policy',fixed_policy_seed=99)
    d=StrategyDefinition.model_validate(data);strategy=DeclarativeStrategy(d);obs=Game(3).observe(0)
    assert strategy.choose(obs,Random(1)).card==strategy.choose(obs,Random(2)).card


def test_api_schema_register_export_and_existing_experiments(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite')) as client:
        catalog=client.get('/api/arena/strategies').json();assert len(catalog['definitions'])==5
        assert 'properties' in client.get('/api/arena/schema').json()
        refs=[d['reference'] for d in catalog['definitions'][:3]]
        request={'participants':refs,'deals':1,'opponents':['Random','Heuristic']}
        assert client.post('/api/arena/estimate',json=request).json()['games']==18
        identifier=client.post('/api/arena/studies',json=request).json()['id']
        import time
        for _ in range(200):
            result=client.get('/api/arena/studies/'+identifier).json()
            if result['status']=='completed':break
            time.sleep(.01)
        assert result['status']=='completed'
        assert client.get('/api/arena/studies/'+identifier+'/export').json()['results']
        assert client.post('/api/arena/definitions',json={**raw(),'shell':'rm'}).status_code==422
        assert client.post('/api/arena/estimate',json={'participants':['Random'],'opponents':['Random','Random'],'deals':True}).status_code==422
        assert client.get('/api/quality-studies').json()==[]
        assert client.get('/api/arena/studies').json()[0]['id']==identifier


def test_arena_cancellation_is_not_completion_and_partial_deal_is_excluded(tmp_path,monkeypatch):
    from threading import Event
    entered=Event()
    def controlled(config,on_row,check,on_partial):
        entered.set()
        while True:
            check()
            Event().wait(.01)
    monkeypatch.setattr(module,'run_arena',controlled)
    jobs=arena_jobs(ExperimentStore(tmp_path/'cancel.sqlite'))
    plan=ArenaPlan(settings=[{'reference':'Random'}],opponent_entries=({'reference':'Random'},{'reference':'Heuristic'}),deal_seeds=[1],analyze_position=False)
    try:
        identifier=jobs.submit(plan)['id'];assert entered.wait(3)
        jobs.cancel(identifier);result=wait(jobs,identifier)
        assert result['status']=='cancelled' and result['completed_games']==0
        assert result['summary']['settings'][0]['average_terminal_reward'] is None
    finally:jobs.close()


def test_arena_search_definition_budget_and_condition_rejections(tmp_path):
    definitions=DefinitionStore(tmp_path/'search.sqlite')
    data=raw();data.update(id='codex_search',selection='theory_search',total_budget=32)
    definition=StrategyDefinition.model_validate(data);definitions.add(definition)
    plan=ArenaRequest(participants=[definition.reference],include_expensive=True,deals=1).resolve(definitions)
    assert arena_estimate(plan)['rollout_upper_bound']==6*15*32+32
    decision=plan.settings[0].create_strategy().choose_detailed(Game(4).observe(0),Random(4))
    assert decision.card in Game(4).observe(0).legal_actions
    assert decision.details.optional_metadata['executed_games']==32
    with pytest.raises(ValueError):ArenaRequest(participants=['Random'],include_expensive='yes')
    with pytest.raises(ValueError):ArenaRequest(participants=['missing@1.0.0']).resolve(definitions)


def test_history_iteration_does_not_hold_database_read_lock(tmp_path):
    store=ExperimentStore(tmp_path/'snapshot.sqlite')
    first=store.save({'value':1});store.save({'value':2})
    iterator=store.iter_experiments();assert next(iterator)[0]==first
    identifier=store.save({'value':3})
    assert store.get(identifier)=={'value':3}
    assert len(list(iterator))==1
