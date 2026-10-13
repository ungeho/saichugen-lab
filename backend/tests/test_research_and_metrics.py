import pytest

from strategy_arena.game.engine import Game
from strategy_arena.research.evaluation import membership_brier
from strategy_arena.experiments.metrics import summarize, wilson
from strategy_arena.strategies.base import Decision
from strategy_arena.strategies.registry import register
from strategy_arena.experiments.runner import run_game


def test_research_only_prediction_evaluation():
    game = Game(4)
    obs = game.observe(0)
    truth = set(game.observe(1).hand)
    perfect = {card: int(card in truth) for card in obs.unseen_cards}
    assert membership_brier(game, 0, 1, perfect) == 0
    constant = {card: 17 / 35 for card in obs.unseen_cards}
    assert membership_brier(game, 0, 1, constant) == pytest.approx(17 / 35 * 18 / 35)
    with pytest.raises(ValueError):
        membership_brier(game, 0, 1, {})


def test_clustered_metrics_known_results():
    results = [{"seed": s, "strategies": ("A", "B", "C"), "scores": (8, 8, 3),
                "winners": (0, 1), "turn_wins": (5, 5, 5), "elapsed_ns": (15000000,) * 3} for s in (1, 2)]
    summary = summarize(results)["strategies"]
    assert summary["A"]["win_rate"] == 1
    assert summary["B"]["ci95"] == [1, 1]
    assert summary["C"]["win_rate"] == 0
    assert summary["A"]["turn_win_rate"] == pytest.approx(1 / 3)
    assert summary["A"]["mean_decision_ms"] == 1
    assert wilson(0, 10)[0] == 0


def test_custom_strategy_registration():
    class FirstCard:
        name = "FirstCardTest"
        version = "1"
        def choose(self, observation, rng):
            return Decision(observation.legal_actions[0])
    register("FirstCardTest", FirstCard)
    game, _ = run_game(10, ("FirstCardTest", "Greedy", "Random"))
    assert game.finished
    with pytest.raises(ValueError):
        register("FirstCardTest", FirstCard)
