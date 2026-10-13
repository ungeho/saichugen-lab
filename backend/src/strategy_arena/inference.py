"""合法的な観測だけを使うカードカウンティングと一様事前分布。"""

from dataclasses import dataclass
from random import Random
from typing import Protocol

from .game.cards import Card
from .game.observation import Observation


@dataclass(frozen=True)
class HandHypothesis:
    hands: tuple[tuple[Card, ...], ...]
    unused: Card


class BeliefSampler(Protocol):
    def sample(self, observation: Observation, rng: Random) -> HandHypothesis: ...


class UniformSampler:
    """行動傾向を考慮しない。実際の非公開手札を参照しない。"""

    def sample(self, observation: Observation, rng: Random) -> HandHypothesis:
        pool = list(observation.unseen_cards)
        expected = sum(n for p, n in enumerate(observation.hand_sizes) if p != observation.player) + 1
        if len(pool) != expected:
            raise ValueError("観測の枚数が整合していません")
        rng.shuffle(pool)
        hands = []
        cursor = 0
        for p, count in enumerate(observation.hand_sizes):
            if p == observation.player:
                hands.append(observation.hand)
            else:
                hands.append(tuple(sorted(pool[cursor:cursor + count])))
                cursor += count
        return HandHypothesis(tuple(hands), pool[-1])
