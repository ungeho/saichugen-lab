"""公開二次資料に基づくカード順序。クラブ < ダイヤ < ハート < スペード。"""

from dataclasses import dataclass
from random import Random


@dataclass(frozen=True, order=True)
class Card:
    rank: int
    suit: int

    def __post_init__(self):
        if type(self.rank) is not int or not 1 <= self.rank <= 13:
            raise ValueError("ランクは1〜13")
        if type(self.suit) is not int or not 0 <= self.suit <= 3:
            raise ValueError("スートは0〜3")

    @property
    def label(self) -> str:
        return "♣♦♥♠"[self.suit] + {1: "A", 11: "J", 12: "Q", 13: "K"}.get(self.rank, str(self.rank))


def deck() -> tuple[Card, ...]:
    return tuple(Card(rank, suit) for rank in range(1, 14) for suit in range(4))


def deal(seed: int) -> tuple[tuple[tuple[Card, ...], ...], Card]:
    cards = list(deck())
    Random(seed).shuffle(cards)
    return tuple(tuple(sorted(cards[p:51:3])) for p in range(3)), cards[51]
