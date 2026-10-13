from copy import deepcopy
from dataclasses import replace, asdict
from random import Random
import json

import pytest

from strategy_arena.game.engine import Game
from strategy_arena.game.rewards import terminal_rewards
from strategy_arena.strategies.hybrid import HybridSearch, METHOD_NAMES, _Expired
from strategy_arena.strategies.baselines import Baseline
from strategy_arena.strategies.registry import create_strategy, algorithm_catalog
from strategy_arena.strategies.base import decide
from strategy_arena.rollouts import sampled_game
from strategy_arena.experiments.rollout_quality import Setting, StudyConfig, run_study, summarize_study, estimate
from strategy_arena.experiments.quality_statistics import compare_saved
from strategy_arena.experiments.quality_jobs import QualityJobs
from strategy_arena.experiments.storage import ExperimentStore
from test_rollout_quality import wait
import strategy_arena.strategies.hybrid as module


@pytest.fixture
def trial_log(monkeypatch):
    calls=[]
    def trial(observation,cards,templates,seed,index,check=lambda:None,policy_names=None,on_game=lambda stage:None):
        assert all(isinstance(p,Baseline) for p in templates)
        assert set(asdict(observation))=={'player','hand','history','round_scores','game_scores','turn','hand_sizes'}
        result=[]
        for c in cards:
            check();on_game('started');calls.append((c,seed,index))
            # 高累計点を優先すると誤る、報酬が唯一の選択基準となる例。
            reward=2 if c.rank==max(x.rank for x in observation.hand) else -1
            result.append(dict(reward=reward,score=-100*reward,sole_win=int(reward==2),joint_win=0))
            on_game('finished')
        return result
    monkeypatch.setattr(module,'rollout_trial',trial)
    return calls


@pytest.mark.parametrize('method',METHOD_NAMES)
def test_budget_minimum_reward_selection_and_crn(method,trial_log):
    game=Game(4);before=deepcopy(game.__dict__);obs=game.observe(0)
    strategy=HybridSearch(method,total_budget=47,min_trials=2)
    d=strategy.choose_detailed(obs,Random(42));meta=d.details.optional_metadata
    assert d.card in obs.legal_actions and d.card.rank==max(c.rank for c in obs.hand)
    assert meta['started_games']==meta['executed_games']==meta['completed_games']==47
    assert meta['unused_budget']==0 and all(c['trials']>=2 for c in meta['candidates'])
    assert sum(c['trials'] for c in meta['candidates'])==47
    assert all(c['reward_ci95'] is None for c in meta['candidates'])
    for candidate in obs.hand:
        indices=[i for c,s,i in trial_log if c==candidate]
        assert indices==list(range(len(indices)))
    if method=='uniform':
        assert max(c['trials'] for c in meta['candidates'])-min(c['trials'] for c in meta['candidates'])<=1
    if method in ('heuristic','combined'):
        scores={c.card:c.score for c in Baseline('Heuristic').choose_detailed(obs,Random(0)).details.candidates}
        assert {c.card:c.components['heuristic_priority_score'] for c in d.details.candidates}==scores
        assert meta['heuristic_ms']>=0
    assert game.__dict__==before


@pytest.mark.parametrize('method',METHOD_NAMES)
def test_reproducible_and_order_invariant(method,trial_log):
    obs=Game(3).observe(1)
    strategy=HybridSearch(method,total_budget=35)
    a=strategy.choose_detailed(obs,Random(9))
    b=strategy.choose_detailed(replace(obs,hand=tuple(reversed(obs.hand))),Random(9))
    assert a.card==b.card and a.details.candidates==b.details.candidates
    assert strategy.choose(obs,Random(9)).card==a.card


@pytest.mark.parametrize('method',METHOD_NAMES)
def test_short_budget_single_action_and_time_zero(method,trial_log):
    obs=Game(0).observe(0)
    low=HybridSearch(method,1).choose_detailed(obs,Random(0))
    assert low.card in obs.legal_actions and low.details.optional_metadata['started_games']==0
    assert all(c.score is None for c in low.details.candidates)
    assert low.details.optional_metadata['unused_budget']==1
    single=HybridSearch(method,64).choose_detailed(replace(obs,hand=(obs.hand[0],)),Random(0))
    assert single.card==obs.hand[0] and not trial_log
    zero=HybridSearch(method,64,time_limit_ms=0).choose_detailed(obs,Random(0))
    assert zero.details.optional_metadata['timed_out'] and zero.details.optional_metadata['started_games']==0


def test_interrupted_initial_cycle_is_not_used(monkeypatch):
    def interrupted(obs,cards,templates,seed,trial,check,*,on_game):
        on_game('started');on_game('finished');on_game('started');raise _Expired
    monkeypatch.setattr(module,'rollout_trial',interrupted)
    d=HybridSearch(total_budget=32).choose_detailed(Game(0).observe(0),Random(1))
    m=d.details.optional_metadata
    assert m['started_games']==2 and m['executed_games']==1 and m['completed_games']==0
    assert m['unused_budget']==30 and m['fallback']


@pytest.mark.parametrize('kwargs',[{'total_budget':0},{'total_budget':1025},{'total_budget':True},
    {'min_trials':0},{'method':'unknown'},{'continuation':'hybrid_adaptive'},
    {'continuation':'monte_carlo_rollout'},{'seed':True},{'time_limit_ms':float('nan')}])
def test_invalid_settings(kwargs):
    with pytest.raises(ValueError):HybridSearch(**kwargs)


def test_observation_sampling_and_real_search_ignore_hidden_cards():
    game=Game(6)
    for _ in range(12):game.play(tuple(game.observe(p).legal_actions[0] for p in range(3)))
    obs=game.observe(0)
    first=sampled_game(obs,Random(7));second=sampled_game(obs,Random(8))
    assert first.observe(0)==second.observe(0)==obs
    assert first.observe(1).hand!=second.observe(1).hand
    for method in METHOD_NAMES:
        strategy=HybridSearch(method,12)
        a=strategy.choose_detailed(first.observe(0),Random(12))
        b=strategy.choose_detailed(second.observe(0),Random(12))
        assert a.card==b.card and a.details.candidates==b.details.candidates
    # 復元世界の全配札は重複せず、公開履歴も再現。
    assert len(set(c for p in range(3) for c in first.observe(p).hand))==15
    assert len({c for hand in first._initial_hands for c in hand}|{first._unused})==52
    assert all(len(first.observe(p).hand)==obs.hand_sizes[p] for p in range(3))
    assert first.observe(0).history==obs.history


def test_registered_strategies_play_together_without_recursive_search():
    names=tuple(METHOD_NAMES.values());assert set(names)<={d['name'] for d in algorithm_catalog()}
    game=Game(10);policies=[HybridSearch(m,32) for m in ('heuristic','adaptive','combined')]
    while not game.finished:
        game.play(tuple(decide(p,game.observe(i),Random(game.observe(i).turn*3+i)).card for i,p in enumerate(policies)))
    assert sum(terminal_rewards(game.winners))==0
    assert all(create_strategy(n).parameters['total_budget']==64 for n in names)


def test_uniform_matches_existing_monte_carlo_when_budget_divisible():
    from strategy_arena.strategies.monte_carlo import MonteCarloRollout
    game=Game(3)
    for _ in range(12):game.play(tuple(game.observe(p).legal_actions[0] for p in range(3)))
    obs=game.observe(0)
    legacy=MonteCarloRollout(trials=3).choose_detailed(obs,Random(7))
    uniform=HybridSearch('uniform',15).choose_detailed(obs,Random(7))
    assert legacy.card==uniform.card
    assert [c.score for c in legacy.details.candidates]==[c.score for c in uniform.details.candidates]


def test_adaptive_changes_allocation_without_eliminating_candidates(trial_log):
    d=HybridSearch('adaptive',128).choose_detailed(Game(1).observe(0),Random(5))
    counts=[c['trials'] for c in d.details.optional_metadata['candidates']]
    assert min(counts)>=1 and max(counts)-min(counts)>1


def test_old_saved_setting_parameters_are_still_accepted():
    from test_rollout_quality import config,synthetic
    cfg=config();rows=synthetic(cfg,0,0,2)+synthetic(cfg,1,0,-1)
    for row in rows:
        for key in ('method','total_budget','min_trials'):row['rollout_parameters'].pop(key)
    summary=summarize_study(cfg,rows)
    assert all(s['independent_deals']==1 for s in summary['settings'])
    assert summary['differences'][0]['difference']==-3


def hybrid_config(budget=20):
    return StudyConfig(settings=[{'method':m,'total_budget':budget} for m in METHOD_NAMES],analyze_position=False)


def test_study_common_conditions_storage_and_legacy_compatibility(tmp_path):
    cfg=hybrid_config();store=ExperimentStore(tmp_path/'hybrid.sqlite');jobs=QualityJobs(store)
    try:
        p=wait(jobs,jobs.submit(cfg)['id']);assert p['status']=='completed'
        assert len(p['results'])==24
        assert json.loads(json.dumps(store.get(p['id'])))==store.get(p['id'])
        summary=p['summary'];assert all(s['independent_deals']==1 for s in summary['settings'])
        assert all(d['comparable'] and d['independent_deals']==1 for d in summary['differences'])
        assert all(s['executed_rollouts']==6*15*20 for s in summary['settings'])
        assert estimate(cfg)['rollout_upper_bound']==24*15*20
        for rows in [p['results'][i:i+4] for i in range(0,24,4)]:
            assert len({(r['seed'],r['rotation'],tuple(r['roles']),r['seat']) for r in rows})==1
            assert len({r['rollout_parameters']['total_budget'] for r in rows})==1
        compared=compare_saved(p,p,cfg.settings[0].identifier,cfg.settings[1].identifier)
        assert compared['comparable'] and compared['difference']==summary['differences'][0]['difference']
        missing=deepcopy(p);missing['runtime']['source_sha256'].pop('strategies/hybrid.py')
        assert not compare_saved(missing,missing,cfg.settings[0].identifier,cfg.settings[1].identifier)['comparable']
        q=deepcopy(p);q['config']['settings']=[{**s,'total_budget':32} for s in q['config']['settings']]
        result=compare_saved(p,q,cfg.settings[0].identifier,Setting.model_validate(q['config']['settings'][1]).identifier)
        assert not result['comparable'] and result['difference'] is None
    finally:jobs.close()


def test_hybrid_study_same_seed_reproduces_outcomes():
    cfg=StudyConfig(settings=[{'method':'adaptive','total_budget':20}],analyze_position=False)
    a=[];b=[];run_study(cfg,a.append);run_study(cfg,b.append)
    clean=lambda rows:[{k:v for k,v in r.items() if k not in ('decisions','game_elapsed_ns')} for r in rows]
    assert clean(a)==clean(b)
    assert [d['executed_rollouts'] for r in a for d in r['decisions']]==[d['executed_rollouts'] for r in b for d in r['decisions']]


@pytest.mark.parametrize('settings',[
    [{'method':'uniform'}], [{'trials':8,'total_budget':32}],
    [{'method':'uniform','total_budget':32},{'method':'adaptive','total_budget':64}],
    [{'trials':8},{'method':'adaptive','total_budget':32}],
    [{'method':'adaptive','total_budget':32,'trials':16}],
])
def test_study_rejects_unequal_budget_or_mixed_modes(settings):
    with pytest.raises(ValueError):StudyConfig(settings=settings)
