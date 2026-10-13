"""3人の選択をまとめて検証・適用する。途中の選択は公開しない。"""

from .cards import Card, deal, deck
from .observation import Observation, PublicTurn
from .rules import ROUNDS_PER_GAME, TURNS_PER_ROUND, median_players, round_awards, turn_winner


class Game:
    def __init__(self, seed: int):
        hands, unused = deal(seed)
        self._initialize(hands, unused)

    def _initialize(self, hands, unused):
        all_cards = [card for hand in hands for card in hand] + [unused]
        if len(hands) != 3 or any(len(hand) != 17 for hand in hands):
            raise ValueError("17枚ずつの3手札が必要")
        if len(all_cards) != 52 or set(all_cards) != set(deck()):
            raise ValueError("52枚のカードが重複なく必要")
        self._initial_hands = tuple(tuple(hand) for hand in hands)
        self._hands = [list(hand) for hand in hands]
        self._unused = unused
        self._history: list[PublicTurn] = []
        self._round_scores = (0, 0, 0)
        self._game_scores = (0, 0, 0)

    @classmethod
    def from_deal(cls, hands, unused):
        game = cls.__new__(cls)
        game._initialize(hands, unused)
        return game

    @property
    def finished(self) -> bool:
        return len(self._history) == ROUNDS_PER_GAME * TURNS_PER_ROUND

    @property
    def winners(self) -> tuple[int, ...]:
        return median_players(self._game_scores) if self.finished else ()

    def observe(self, player: int) -> Observation:
        if type(player) is not int or player not in range(3):
            raise ValueError("不正なプレイヤー")
        return Observation(player, tuple(self._hands[player]), tuple(self._history),
                           self._round_scores, self._game_scores, len(self._history),
                           tuple(len(hand) for hand in self._hands))

    def play(self, actions: tuple[Card, Card, Card]) -> PublicTurn:
        if self.finished:
            raise ValueError("ゲームは終了済み")
        if len(actions) != 3 or any(card not in self._hands[p] for p, card in enumerate(actions)):
            raise ValueError("各プレイヤーの手札から1枚ずつ選択してください")
        winner = turn_winner(actions)
        scores = list(self._round_scores)
        scores[winner] += actions[winner].rank
        completed = (len(self._history) + 1) % TURNS_PER_ROUND == 0
        totals = self._game_scores
        if completed:
            awards = round_awards(tuple(scores))
            totals = tuple(totals[p] + awards[p] for p in range(3))
        event = PublicTurn(len(self._history), tuple(actions), winner, tuple(scores), totals)
        for p, card in enumerate(actions):
            self._hands[p].remove(card)
        self._history.append(event)
        self._game_scores = totals
        self._round_scores = (0, 0, 0) if completed else tuple(scores)
        return event
