from random import Random

from .base import Decision
from ..game.cards import Card
from ..game.observation import Observation

NAMES = ("Random", "Greedy", "Conservative", "ScoreAware", "Heuristic")


def middle_probability(card: Card, observation: Observation) -> float:
    """相手が未知札から無作為に出す基準モデルで、中位になる確率を厳密計算。"""
    pool = observation.unseen_cards
    lower = sum(c < card for c in pool)
    higher = len(pool) - lower
    return 2 * lower * higher / (len(pool) * (len(pool) - 1))


class Baseline:
    version = "1"

    def __init__(self, name: str):
        if name not in NAMES:
            raise ValueError("未知の戦略")
        self.name = name

    def choose(self, observation: Observation, rng: Random) -> Decision:
        legal = observation.legal_actions
        if not legal:
            raise ValueError("選択できるカードがありません")
        if self.name == "Random":
            return Decision(rng.choice(legal), explanation="合法手から一様選択")
        probabilities = {c: middle_probability(c, observation) for c in legal}
        desire = 1.0 if self.name == "Greedy" else -1.0
        if self.name in ("ScoreAware", "Heuristic"):
            scores = observation.round_scores
            target = sorted(scores)[1]
            own = scores[observation.player]
            desire = 1.0 if own <= target else -1.0
            if self.name == "Heuristic":
                # ゲーム得点が過大なら低得点のラウンド勝利を目指す。
                totals = observation.game_scores
                if totals[observation.player] > sorted(totals)[1]:
                    desire = -1.0
        def value(card):
            probability = probabilities[card]
            if self.name != "Heuristic":
                return desire * probability
            # 中位からの距離と、温存するカードの選択自由度を粗く評価。
            own = observation.round_scores[observation.player]
            others = [s for p, s in enumerate(observation.round_scores) if p != observation.player]
            target = sum(others) / 2 + (2 - observation.turn % 3) * 3
            distance = probability * abs(own + card.rank - target) + (1 - probability) * abs(own - target)
            future = sum(abs(c.rank - 7) for c in legal if c != card) / max(1, len(legal) - 1)
            return desire * probability - distance / 13 + future * 0.03
        values = {c: value(c) for c in legal}
        best = max(values.values())
        chosen = rng.choice([c for c in legal if abs(values[c] - best) < 1e-12])
        return Decision(chosen, desire, probabilities[chosen], "未知札一様モデルによる比較用評価")
