from copy import deepcopy
from dataclasses import replace,asdict
from random import Random
import json

import pytest
from fastapi.testclient import TestClient

from strategy_arena.api.app import create_app
from strategy_arena.game.cards import Card
from strategy_arena.game.engine import Game
from strategy_arena.rollouts import sampled_game
from strategy_arena.strategies.theories import TheorySpec,TheoryConfig,theory_catalog,evaluate_theory,evaluate_combination
from strategy_arena.strategies.theory_policy import TheoryPolicy,TheorySearch
from strategy_arena.strategies.hybrid import HybridSearch
from strategy_arena.strategies.baselines import Baseline
from strategy_arena.strategies.registry import create_strategy
from strategy_arena.experiments.rollout_quality import StudyConfig,run_study,estimate
from strategy_arena.experiments.quality_jobs import QualityJobs
from strategy_arena.experiments.quality_statistics import compare_saved
from strategy_arena.experiments.storage import ExperimentStore
from test_rollout_quality import wait


def spec(id,**kw):return TheorySpec(id=id,**kw)
def cfg(*specs):return TheoryConfig(theories=list(specs))
def observation():
    game=Game(42)
    for _ in range(9):game.play(tuple(game.observe(p).legal_actions[0] for p in range(3)))
    return game.observe(0)


@pytest.mark.parametrize('id',[d['id'] for d in theory_catalog()])
def test_theories_are_deterministic_bounded_disabled_and_only_use_observation(id):
    obs=observation();before=asdict(obs);s=spec(id)
    values=[evaluate_theory(obs,c,s) for c in obs.legal_actions]
    assert values==[evaluate_theory(obs,c,s) for c in obs.legal_actions]
    assert all(-1<=r['value']<=1 for r in values)
    assert all(evaluate_theory(obs,c,s.model_copy(update={'enabled':False}))['value']==0 for c in obs.hand)
    assert all(not evaluate_theory(obs,c,s.model_copy(update={'weight':0}))['applicable'] for c in obs.hand)
    assert asdict(obs)==before
    a=sampled_game(obs,Random(4));b=sampled_game(obs,Random(5))
    assert a.observe(1).hand!=b.observe(1).hand
    assert evaluate_combination(a.observe(0),cfg(s))==evaluate_combination(b.observe(0),cfg(s))


def test_preserve_consume_and_last_turn_inapplicability():
    obs=replace(observation(),hand=(Card(2,0),Card(7,1),Card(13,3)))
    for id,desired in [('reserve_strong',Card(13,3)),('reserve_middle',Card(7,1))]:
        hold=TheoryPolicy(cfg(spec(id))).choose(obs,Random(1))
        use=TheoryPolicy(cfg(spec(id,params={'mode':'consume'}))).choose(obs,Random(1))
        assert hold.card!=desired and use.card==desired
        assert not evaluate_theory(replace(obs,turn=14),obs.hand[0],spec(id))['applicable']


def test_round_combination_and_cumulative_are_distance_proxies():
    obs=replace(observation(),round_scores=(10,8,15),game_scores=(10,0,20))
    card=obs.hand[0]
    r=evaluate_theory(obs,card,spec('round_focus',params={'mode':'round'}))
    g=evaluate_theory(obs,card,spec('round_focus',params={'mode':'cumulative'}))
    both=evaluate_theory(obs,card,spec('round_focus',params={'mode':'both'}))
    assert both['value']==pytest.approx((r['value']+g['value'])/2)
    near=evaluate_theory(replace(obs,game_scores=(10,0,20)),card,spec('cumulative_target'))
    high=evaluate_theory(replace(obs,game_scores=(100,0,20)),card,spec('cumulative_target'))
    assert near['value']>high['value'] # 高累計を単純に好まない


def test_memory_off_ignores_history_and_strength_zero_is_uniform():
    obs=observation();card=obs.hand[0]
    off=spec('public_memory',params={'public':False})
    assert evaluate_theory(obs,card,off)==evaluate_theory(replace(obs,history=()),card,off)
    on=evaluate_theory(obs,card,spec('public_memory'))
    assert on['components']['pool_size']<evaluate_theory(obs,card,off)['components']['pool_size']
    model=evaluate_theory(obs,card,spec('opponent_targets',params={'strength':0}))
    assert abs(model['value'])==pytest.approx(on['value'])


def test_weighted_contributions_order_invariance_and_no_theory_control():
    obs=observation();config=cfg(spec('reserve_strong',weight=2),spec('round_focus',weight=-1))
    decision=TheoryPolicy(config).choose_detailed(obs,Random(3))
    meta=decision.details.optional_metadata
    assert all(row['score']==pytest.approx(sum(t['contribution'] for t in row['terms'])) for row in meta['evaluations'])
    assert all(t['contribution']==pytest.approx(t['value']*t['weight']/3) for row in meta['evaluations'] for t in row['terms'])
    reverse=TheoryPolicy(config).choose_detailed(replace(obs,hand=tuple(reversed(obs.hand))),Random(3))
    assert decision==reverse
    control=TheoryPolicy(cfg()).choose_detailed(obs,Random(3))
    assert all(c.score==0 for c in control.details.candidates)
    assert control.card==Random(3).choice(sorted(obs.hand))


def test_omitted_defaults_and_numeric_spellings_have_stable_setting_ids(tmp_path):
    from strategy_arena.experiments.rollout_quality import Setting
    first=Setting.model_validate({'method':'theory','theory_config':{'theories':[{'id':'reserve_strong'}]}})
    loaded=Setting.model_validate_json(first.model_dump_json())
    explicit=Setting.model_validate({'method':'theory','theory_config':{'theories':[{'id':'reserve_strong','weight':1,'params':{'threshold':10.0}}]}})
    assert first.identifier==loaded.identifier==explicit.identifier
    config=StudyConfig(settings=[first],seed_partition='development',analyze_position=False)
    jobs=QualityJobs(ExperimentStore(tmp_path/'defaults.sqlite'))
    try:
        result=wait(jobs,jobs.submit(config)['id'])
        assert result['status']=='completed' and result['summary']['settings'][0]['independent_deals']==1
    finally:jobs.close()


@pytest.mark.parametrize('payload',[
    {'id':'unknown'}, {'id':'public_memory','version':'2'}, {'id':'reserve_strong','params':{'unknown':1}},
    {'id':'reserve_strong','params':{'threshold':99}}, {'id':'reserve_middle','params':{'mode':'bad'}},
    {'id':'public_memory','params':{'public':1}}, {'id':'opponent_targets','params':{'strength':float('nan')}},
    {'id':'public_memory','weight':3},{'id':'public_memory','weight':True},{'id':'public_memory','enabled':1},
])
def test_invalid_theory_config(payload):
    with pytest.raises(ValueError):TheorySpec.model_validate(payload)


def test_duplicate_illegal_action_and_seed_partition_rejected():
    with pytest.raises(ValueError):cfg(spec('reserve_strong'),spec('reserve_strong'))
    obs=observation();illegal=next(c for c in obs.unseen_cards)
    with pytest.raises(ValueError):evaluate_theory(obs,illegal,spec('public_memory'))
    setting={'method':'theory','theory_config':cfg(spec('reserve_strong')).model_dump()}
    for partition,seeds in [('unassigned',[0]),('validation',[0]),('final',[1000000]),('development',[1000000])]:
        with pytest.raises(ValueError):StudyConfig(settings=[setting],seed_partition=partition,deal_seeds=seeds)
    for partition,seeds in [('development',[0]),('validation',[1000000]),('final',[2000000])]:
        assert StudyConfig(settings=[setting],seed_partition=partition,deal_seeds=seeds).seed_partition==partition


def test_priority_injection_uses_same_hybrid_budget_and_preserves_default():
    obs=observation()
    for adaptive in (False,True):
        strategy=TheorySearch(cfg(spec('public_memory')),adaptive=adaptive,total_budget=24)
        a=strategy.choose_detailed(obs,Random(42));b=strategy.choose_detailed(obs,Random(42))
        assert a.card==b.card and a.details.candidates==b.details.candidates
        meta=a.details.optional_metadata
        assert meta['started_games']==meta['executed_games']==24
        assert all(c['trials']>=1 for c in meta['candidates'])
        assert meta['priority_evaluations'] and meta['priority_source']['theory_config']
        assert a.card==max(a.details.candidates,key=lambda c:c.score).card
    class Existing:
        parameters={}
        def evaluate(self,obs):
            d=Baseline('Heuristic').choose_detailed(obs,Random(0))
            return {c.card:c.score for c in d.details.candidates},[]
    first=HybridSearch('combined',24).choose_detailed(obs,Random(8))
    second=HybridSearch('combined',24,priority_evaluator=Existing()).choose_detailed(obs,Random(8))
    assert first.card==second.card
    assert [c.score for c in first.details.candidates]==[c.score for c in second.details.candidates]
    assert all(create_strategy(n).name==n for n in ('theory_policy','theory_search','theory_search_adaptive'))


def test_api_observation_boundary_and_configuration_validation(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite')) as client:
        catalog=client.get('/api/theories').json();assert len(catalog)==6
        assert all(d['status']=='未検証の仮説' for d in catalog)
        body={'config':cfg(spec('opponent_targets')).model_dump(),'seed':12,'turn':9}
        a=client.post('/api/theories/evaluate',json=body).json();b=client.post('/api/theories/evaluate',json=body).json()
        assert a==b
        assert set(a['observation'])=={'player','hand','history','round_scores','game_scores','turn','hand_sizes'}
        assert 'theory_policy' in [d['name'] for d in client.get('/api/algorithms').json()]
        assert client.post('/api/theories/evaluate',json={**body,'turn':15}).status_code==422
        assert client.post('/api/theories/evaluate',json={'config':{'theories':[{'id':'bad'}]}}).status_code==422


def test_study_reproducibility_storage_export_comparison_and_trends(tmp_path):
    settings=[{'method':'theory','theory_config':cfg(spec('reserve_strong',enabled=False)).model_dump()},
              {'method':'theory','theory_config':cfg(spec('reserve_strong')).model_dump()},
              {'method':'baseline','baseline_name':'Greedy'}]
    config=StudyConfig(settings=settings,seed_partition='development',analyze_position=True)
    store=ExperimentStore(tmp_path/'study.sqlite');jobs=QualityJobs(store)
    try:
        a=wait(jobs,jobs.submit(config)['id']);b=wait(jobs,jobs.submit(config)['id'])
        assert a['status']==b['status']=='completed' and len(a['results'])==18
        clean=lambda p:[{k:v for k,v in r.items() if k not in ('game_elapsed_ns','decisions')} for r in p['results']]
        assert clean(a)==clean(b)
        assert estimate(config)['rollout_upper_bound']==0
        assert all(s['independent_deals']==1 and s['reward_ci95'] is None for s in a['summary']['settings'])
        assert all(d['comparable'] for d in a['summary']['differences'])
        assert all(s['executed_rollouts']==0 for s in a['summary']['settings'])
        assert sum(t['decisions'] for t in a['summary']['settings'][0]['decision_trends'] if t['dimension']=='phase')==90
        assert a['strategy_manifest'][1]['theories']['theories'][0]['id']=='reserve_strong'
        saved=store.get(a['id']);assert json.loads(json.dumps(saved))==saved
        result=compare_saved(a,b,config.settings[0].identifier,config.settings[1].identifier)
        assert result['comparable']
        bad=deepcopy(b);bad['config']['seed_partition']='validation';bad['config']['deal_seeds']=[1000000]
        assert not compare_saved(a,bad,config.settings[0].identifier,config.settings[1].identifier)['comparable']
        with TestClient(create_app(store.path)) as client:
            exported=client.get('/api/quality-studies/'+a['id']+'/export').json()
            assert exported['results']==json.loads(json.dumps(a['results']))
        assert store.get(a['id'])==saved
    finally:jobs.close()
