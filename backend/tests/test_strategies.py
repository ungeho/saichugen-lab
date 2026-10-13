from random import Random

import pytest

from strategy_arena.game.engine import Game
from strategy_arena.experiments.runner import run_game, run_experiment
from strategy_arena.research.replay import export_full
from strategy_arena.strategies.baselines import Baseline, NAMES, middle_probability


@pytest.mark.parametrize("name", NAMES)
def test_baselines_complete_and_reproduce(name):
    game, trace = run_game(42, (name, name, name))
    duplicate, trace2 = run_game(42, (name, name, name))
    assert game.finished
    assert export_full(game) == export_full(duplicate)
    assert [t["decisions"] for t in trace] == [t["decisions"] for t in trace2]


def test_probabilities_against_pair_enumeration():
    from itertools import combinations
    observation = Game(1).observe(0)
    for card in observation.hand:
        pairs = list(combinations(observation.unseen_cards, 2))
        actual = sum(sorted((card, a, b))[1] == card for a, b in pairs) / len(pairs)
        assert middle_probability(card, observation) == pytest.approx(actual)


def test_all_seat_permutations_share_seed():
    results = run_experiment([12], ("Random", "Greedy", "Conservative"))
    assert len(results) == 6
    assert {r["seed"] for r in results} == {12}
    assert len({r["strategies"] for r in results}) == 6
