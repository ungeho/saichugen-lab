from copy import deepcopy
from dataclasses import replace, asdict, fields
from random import Random

import pytest
from fastapi.testclient import TestClient

from strategy_arena.api.app import create_app
from strategy_arena.game.engine import Game
from strategy_arena.game.observation import Observation
from strategy_arena.game.rewards import terminal_rewards
from strategy_arena.rollouts import sampled_game, rollout_trial
from strategy_arena.strategies.baselines import Baseline
from strategy_arena.strategies.monte_carlo import MonteCarloRollout, MAX_TRIALS, _BudgetExpired
from strategy_arena.strategies.registry import create_strategy, algorithm_catalog
from strategy_arena.experiments.runner import run_experiment, derived_seed
from strategy_arena.branch_simulation import simulate
import strategy_arena.strategies.monte_carlo as module


def position(turn=12, player=0):
    game = Game(42)
    for _ in range(turn):
        game.play(tuple(game.observe(p).hand[0] for p in range(3)))
    return game.observe(player)


def stable(decision):
    result = asdict(decision)
    result['details']['optional_metadata'].pop('elapsed_ms')
    return result


@pytest.mark.parametrize('player', range(3))
def test_legal_deterministic_order_and_capture_independent(player):
    obs = position(player=player)
    before = deepcopy(obs)
    strategy = MonteCarloRollout(trials=3)
    rng1, rng2 = Random(5), Random(5)
    plain = strategy.choose(obs, rng1)
    detail = strategy.choose_detailed(obs, rng2)
    assert plain.details is None
    assert plain.card == detail.card in obs.legal_actions
    assert rng1.getstate() == rng2.getstate()
    assert stable(detail) == stable(strategy.choose_detailed(obs, Random(5)))
    assert stable(detail) == stable(strategy.choose_detailed(replace(obs, hand=obs.hand[::-1]), Random(5)))
    assert obs == before
    candidates = detail.details.candidates
    assert next(c.score for c in candidates if c.card == detail.card) == max(c.score for c in candidates)


def test_one_legal_card_and_finished_observation(monkeypatch):
    monkeypatch.setattr(module, 'rollout_trial', lambda *args: pytest.fail('unnecessary rollout'))
    obs = position()
    decision = MonteCarloRollout().choose_detailed(replace(obs, hand=obs.hand[:1]), Random(1))
    assert decision.card == obs.hand[0]
    assert decision.details.candidates[0].score is None
    assert decision.details.optional_metadata['completed_games'] == 0
    with pytest.raises(ValueError):
        MonteCarloRollout().choose(replace(obs, turn=15), Random(1))


def test_objective_is_reward_not_score_or_win_rate(monkeypatch):
    obs = replace(position(), hand=position().hand[:2])
    def fake(observation, cards, templates, seed, trial, check, **kwargs):
        return [dict(reward=1, score=0, sole_win=0, joint_win=1),
                dict(reward=-1, score=1000, sole_win=1, joint_win=0)]
    monkeypatch.setattr(module, 'rollout_trial', fake)
    decision = MonteCarloRollout(trials=2).choose_detailed(obs, Random(1))
    assert decision.card == sorted(obs.hand)[0]
    assert decision.details.candidates[0].score == 1
    assert decision.details.optional_metadata['best_vs_runner_up']['average_terminal_reward_difference'] == 2


def test_same_observation_different_real_hidden_hands():
    obs = position()
    first, second = sampled_game(obs, Random(1)), sampled_game(obs, Random(2))
    assert first.observe(1).hand != second.observe(1).hand
    assert first.observe(0) == second.observe(0) == obs
    strategy = MonteCarloRollout(trials=2, seed=10)
    assert stable(strategy.choose_detailed(first.observe(0), Random(1))) == stable(strategy.choose_detailed(second.observe(0), Random(999)))


def test_world_constraints_and_common_random_numbers():
    obs = position(7, 1)
    cards = sorted(obs.hand)[:3]
    templates = [Baseline('Random') for _ in range(3)]
    for trial in range(3):
        world = sampled_game(obs, Random(derived_seed(10, f'branch-world:{trial}')))
        assert world.observe(1) == obs
        remaining = [c for p in range(3) for c in world.observe(p).hand]
        public = [c for t in obs.history for c in t.cards]
        assert len(set(remaining + public + [world._unused])) == 52
        assert tuple(len(world.observe(p).hand) for p in range(3)) == obs.hand_sizes
        forward = rollout_trial(obs, cards, templates, 10, trial)
        reverse = rollout_trial(obs, cards[::-1], templates, 10, trial)
        assert forward == reverse[::-1]
    assert all(s.name == 'Random' for s in templates)


def test_shared_branch_results_and_terminal_reward_statistics():
    obs = position(14)
    strategy = MonteCarloRollout(trials=4, seed=17)
    decision = strategy.choose_detailed(obs, Random(1))
    result = simulate(obs, {}, tuple(sorted(obs.hand)), ('Random',)*3, 4, 17)
    for stat, branch in zip(decision.details.optional_metadata['candidates'], result['candidates']):
        for key in ('trials','average_terminal_reward','sole_win_rate','joint_win_rate','average_score'):
            assert stat[key] == branch[key]
        assert -2 <= stat['average_terminal_reward'] <= 2
        assert stat['reward_ci95'] is not None
    one = MonteCarloRollout(trials=1).choose_detailed(obs, Random(1))
    assert all(s['reward_ci95'] is None for s in one.details.optional_metadata['candidates'])


@pytest.mark.parametrize('settings', [
    {'trials':0}, {'trials':True}, {'trials':MAX_TRIALS+1}, {'trials':1.5},
    {'continuation':'monte_carlo_rollout'}, {'continuation':'missing'},
    {'seed':True}, {'seed':'3'}, {'time_limit_ms':-1}, {'time_limit_ms':5001},
    {'time_limit_ms':float('nan')}, {'time_limit_ms':True},
])
def test_invalid_parameters(settings):
    with pytest.raises(ValueError):
        MonteCarloRollout(**settings)


def test_timeout_fallback_and_incomplete_trials_discarded(monkeypatch):
    obs = position()
    empty = MonteCarloRollout(time_limit_ms=0).choose_detailed(obs, Random(1))
    assert empty.card == min(obs.hand)
    assert empty.details.optional_metadata['timed_out']
    assert all(c.score is None for c in empty.details.candidates)
    def fake(observation, cards, templates, seed, trial, check, **kwargs):
        if trial == 1:
            raise _BudgetExpired
        return [dict(reward=0, score=0, sole_win=0, joint_win=1) for c in cards]
    monkeypatch.setattr(module, 'rollout_trial', fake)
    partial = MonteCarloRollout(trials=4).choose_detailed(obs, Random(1))
    assert partial.details.optional_metadata['completed_trials'] == 1
    assert all(c.components['trials'] == 1 for c in partial.details.candidates)


def test_continuations_receive_only_own_observation_and_no_recursion(monkeypatch):
    original = Baseline.choose
    calls = []
    def checked(self, obs, rng):
        assert type(obs) is Observation
        assert {f.name for f in fields(obs)} == {'player','hand','history','round_scores','game_scores','turn','hand_sizes'}
        calls.append((self.name, obs.player))
        return original(self, obs, rng)
    monkeypatch.setattr(Baseline, 'choose', checked)
    MonteCarloRollout(trials=1, continuation='Conservative').choose(position(13), Random(1))
    assert {name for name,p in calls} == {'Conservative'}
    assert {p for name,p in calls} == {0,1,2}


@pytest.mark.parametrize('name', ['Random','Greedy','Conservative','ScoreAware','Heuristic'])
def test_all_lightweight_continuations(name):
    obs = position(14)
    assert MonteCarloRollout(trials=1, continuation=name).choose(obs, Random(1)).card in obs.hand


def test_maximum_trial_budget_is_exact(monkeypatch):
    calls = []
    def fake(obs, cards, templates, seed, trial, check, **kwargs):
        calls.append(trial)
        return [dict(reward=0, score=0, sole_win=0, joint_win=1) for c in cards]
    monkeypatch.setattr(module, 'rollout_trial', fake)
    decision = MonteCarloRollout(trials=MAX_TRIALS).choose_detailed(position(), Random(1))
    assert calls == list(range(MAX_TRIALS))
    assert decision.details.optional_metadata['completed_games'] == MAX_TRIALS * len(position().hand)


def test_registered_api_comparison_spectating_and_experiment(tmp_path):
    name = MonteCarloRollout.name
    assert type(create_strategy(name)) is MonteCarloRollout
    description = next(a for a in algorithm_catalog() if a['name'] == name)
    assert description['description_available'] and 'MCTS' in description['implementation']
    with TestClient(create_app(tmp_path/'rollout.sqlite')) as client:
        game = client.post('/api/games', json={'strategies':[name,'Random','Greedy']}).json()
        identifier = game['id']
        before = client.get(f"/api/games/{identifier}").json()
        compared = client.post(f"/api/games/{identifier}/compare", json={'strategies':[name], 'seed':7}).json()
        assert compared['results'][0]['status'] == 'ok'
        assert client.get(f"/api/games/{identifier}").json() == before
        for _ in range(15):
            game = client.post(f"/api/games/{identifier}/step").json()
        assert game['finished'] and game['terminal_rewards'] == list(terminal_rewards(game['winners']))
        result = client.post('/api/experiments', json={'strategies':[name,'Random','Greedy'], 'deals':1, 'rotate':False}).json()
        assert result['strategy_parameters'][name]['trials'] == 8
        assert result['summary']['strategies'][name]['reward_games'] == 1
    rows = run_experiment([2], (name,)*3, rotate=False)
    assert len(rows) == 1 and sum(rows[0]['terminal_rewards']) == 0
