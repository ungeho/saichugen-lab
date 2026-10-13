from dataclasses import dataclass
from random import Random
from typing import Protocol

from ..game.cards import Card
from ..game.observation import Observation


@dataclass(frozen=True)
class CandidateEvaluation:
    card: Card
    score: float | None = None
    explanation: str = ""
    components: dict[str, float] | None = None


@dataclass(frozen=True)
class DecisionDetails:
    """選択時の計算記録。評価しない戦略はscoreをNoneのままにする。"""

    candidates: tuple[CandidateEvaluation, ...] = ()
    reasoning: tuple[str, ...] = ()
    score_label: str = "評価値は提供されていません"
    information_used: tuple[str, ...] = ()
    estimates: tuple[str, ...] = ()
    optional_metadata: dict | None = None
    origin: str = "選択時の計算記録"


@dataclass(frozen=True)
class Decision:
    card: Card
    desire_to_win: float | None = None
    estimated_turn_win: float | None = None
    explanation: str = ""
    details: DecisionDetails | None = None


class Strategy(Protocol):
    name: str
    version: str

    def choose(self, observation: Observation, rng: Random) -> Decision: ...


def decide(strategy: Strategy, observation: Observation, rng: Random, capture_details: bool = False) -> Decision:
    """chooseを維持し、任意実装のchoose_detailedをログ有効時だけ呼ぶ。再計算しない。"""
    detailed = getattr(strategy, "choose_detailed", None)
    if capture_details and callable(detailed):
        return detailed(observation, rng)
    return strategy.choose(observation, rng)


def decision_record(decision: Decision, observation: Observation, capture_details: bool) -> dict:
    from dataclasses import asdict

    record = asdict(decision)
    if not capture_details:
        record.pop("details", None)
        record["details_status"] = "disabled"
        return record
    record["details_status"] = "available" if decision.details else "not_provided"
    # 実行環境が記録する判断時点の文脈。戦略が全項目を使ったという意味ではない。
    record["context"] = {
        "player": observation.player, "turn": observation.turn,
        "round_scores": observation.round_scores, "game_scores": observation.game_scores,
        "hand_sizes": observation.hand_sizes, "public_history_length": len(observation.history),
        "unseen_count": len(observation.unseen_cards), "origin": "実行環境が記録した判断時点の情報",
    }
    return record
