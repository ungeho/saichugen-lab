"""GPCC資料・公開二次資料に基づく単一のルール実装。"""

from .cards import Card

RULE_VERSION = "gpcc-public-secondary-v1"
TURNS_PER_ROUND = 3
ROUNDS_PER_GAME = 5


def median_players(scores: tuple[int, int, int]) -> tuple[int, ...]:
    if len(scores) != 3:
        raise ValueError("プレイヤーは3人")
    middle = sorted(scores)[1]
    return tuple(p for p, score in enumerate(scores) if score == middle)


def turn_winner(cards: tuple[Card, Card, Card]) -> int:
    if len(cards) != 3 or len(set(cards)) != 3:
        raise ValueError("異なるカード3枚が必要")
    return sorted(range(3), key=lambda p: cards[p])[1]


def round_awards(scores: tuple[int, int, int]) -> tuple[int, int, int]:
    winners = median_players(scores)
    return tuple(score if p in winners else 0 for p, score in enumerate(scores))
