"""Strategyに渡す、完全状態への参照を持たない不変の観測。"""

from dataclasses import dataclass

from .cards import Card, deck


@dataclass(frozen=True)
class PublicTurn:
    index: int
    cards: tuple[Card, Card, Card]
    winner: int
    round_scores: tuple[int, int, int]
    game_scores: tuple[int, int, int]


@dataclass(frozen=True)
class Observation:
    player: int
    hand: tuple[Card, ...]
    history: tuple[PublicTurn, ...]
    round_scores: tuple[int, int, int]
    game_scores: tuple[int, int, int]
    turn: int
    hand_sizes: tuple[int, int, int]

    @property
    def legal_actions(self) -> tuple[Card, ...]:
        return self.hand if self.turn < 15 else ()

    @property
    def unseen_cards(self) -> tuple[Card, ...]:
        known = set(self.hand)
        known.update(card for event in self.history for card in event.cards)
        return tuple(card for card in deck() if card not in known)

    def actions_by(self, player: int) -> tuple[Card, ...]:
        if player not in range(3):
            raise ValueError("不正なプレイヤー")
        return tuple(event.cards[player] for event in self.history)
