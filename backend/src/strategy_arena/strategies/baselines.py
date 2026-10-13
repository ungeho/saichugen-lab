from random import Random

from .base import CandidateEvaluation, Decision, DecisionDetails
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
        return self._choose(observation, rng, False)

    def choose_detailed(self, observation: Observation, rng: Random) -> Decision:
        return self._choose(observation, rng, True)

    def _choose(self, observation: Observation, rng: Random, capture: bool) -> Decision:
        legal = observation.legal_actions
        if not legal:
            raise ValueError("選択できるカードがありません")
        if self.name == "Random":
            chosen = rng.choice(legal)
            details = None
            if capture:
                details = DecisionDetails(
                    candidates=tuple(CandidateEvaluation(c, explanation="評価点は付けず、他の合法手と同じ確率で選択") for c in legal),
                    reasoning=(f"出せる{len(legal)}枚を確認しました。", f"各カードを1/{len(legal)}の確率で選び、{chosen.label}を引きました。"),
                    score_label="評価関数なし（一様な無作為選択）", information_used=("自分の合法手",),
                    optional_metadata={"selection_probability": 1 / len(legal)},
                )
            return Decision(chosen, explanation="合法手から一様選択", details=details)
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
        candidates = [] if capture else None
        def value(card):
            probability = probabilities[card]
            if self.name != "Heuristic":
                result = desire * probability
                if capture:
                    candidates.append(CandidateEvaluation(card, result,
                        f"基準モデルの獲得確率は{probability:.1%}。" +
                        ("このターンを取りたいので、高い確率ほど優先します。" if desire > 0 else "このターンを譲りたいので、低い確率ほど優先します。"),
                        {"turn_win_probability": probability, "desire": desire}))
                return result
            # 中位からの距離と、温存するカードの選択自由度を粗く評価。
            own = observation.round_scores[observation.player]
            others = [s for p, s in enumerate(observation.round_scores) if p != observation.player]
            target = sum(others) / 2 + (2 - observation.turn % 3) * 3
            distance = probability * abs(own + card.rank - target) + (1 - probability) * abs(own - target)
            future = sum(abs(c.rank - 7) for c in legal if c != card) / max(1, len(legal) - 1)
            result = desire * probability - distance / 13 + future * 0.03
            if capture:
                candidates.append(CandidateEvaluation(card, result,
                    f"獲得確率{probability:.1%}に加え、目標{target:.1f}点との予想差{distance:.2f}点を考慮。"
                    f"残す札のランク7からの平均距離は{future:.2f}です。予想差が小さく、残す札の基準が大きいほど加点します。",
                    {"turn_win_probability": probability, "desire": desire, "target_score": target,
                     "expected_distance": distance, "remaining_rank_distance": future,
                     "win_term": desire * probability, "distance_term": -distance / 13, "hand_term": future * 0.03}))
            return result
        values = {c: value(c) for c in legal}
        best = max(values.values())
        chosen = rng.choice([c for c in legal if abs(values[c] - best) < 1e-12])
        details = None
        explanation = "未知札一様モデルによる比較用評価"
        if capture:
            information = ["自分の手札", "公開済みカードから求めた未知札", "カードの順位"]
            reasoning = []
            if self.name in ("ScoreAware", "Heuristic"):
                information.append("現在のラウンド得点")
                reasoning.append(f"ラウンド得点{observation.round_scores}とその中央値{sorted(observation.round_scores)[1]}を確認しました。")
            if self.name == "Heuristic":
                information += ["ゲーム得点", "ラウンド内の残りターン数", "選択後に残る手札"]
                reasoning.append(f"ゲーム得点{observation.game_scores}も確認し、獲得・回避の方針を決めました。")
            reasoning.append("このターンは獲得を優先します。" if desire > 0 else "このターンは獲得を避けます。")
            reasoning.append(f"{len(legal)}枚について未知札一様モデルの獲得確率を計算しました。")
            if self.name == "Heuristic":
                target = candidates[0].components["target_score"]
                reasoning.append(f"目標を{target:.1f}点に置き、獲得・回避の方針、目標からの予想距離、残す札の基準を実装の固定係数で合算しました。")
            tied = sum(abs(score - best) < 1e-12 for score in values.values())
            explanation = f"最大評価{best:.6f}の候補{tied}枚から無作為に{chosen.label}を選択しました。"
            reasoning.append(explanation)
            details = DecisionDetails(
                candidates=tuple(candidates), reasoning=tuple(reasoning),
                score_label="独自の加重評価（大きいほど優先）" if self.name == "Heuristic" else "方針×中位になる確率（大きいほど優先）",
                information_used=tuple(information),
                estimates=("相手が出す2枚を、未知札から重複なく一様に選ぶ基準モデルです。",
                           "実際の相手手札・行動の癖を推定した確率ではありません。"),
                optional_metadata={"tie_count": tied, "tie_tolerance": 1e-12},
            )
        return Decision(chosen, desire, probabilities[chosen], explanation, details)
