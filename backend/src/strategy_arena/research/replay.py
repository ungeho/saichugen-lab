"""研究者が明示的に使う完全リプレイの保存・再検証。"""

from ..game.cards import Card
from ..game.engine import Game
from ..game.rules import RULE_VERSION


def export_full(game: Game) -> dict:
    def encode(card):
        return [card.rank, card.suit]
    return {
        "schema_version": 1,
        "rule_version": RULE_VERSION,
        "visibility_version": "private-hands-v1",
        "initial_hands": [[encode(c) for c in hand] for hand in game._initial_hands],
        "unused": encode(game._unused),
        "actions": [[encode(c) for c in turn.cards] for turn in game._history],
    }


def replay(data: dict) -> Game:
    if (data["schema_version"] != 1 or data["rule_version"] != RULE_VERSION
            or data["visibility_version"] != "private-hands-v1"):
        raise ValueError("非対応のリプレイ形式・ルール・公開仕様")
    hands = tuple(tuple(Card(*c) for c in hand) for hand in data["initial_hands"])
    game = Game.from_deal(hands, Card(*data["unused"]))
    for turn in data["actions"]:
        game.play(tuple(Card(*c) for c in turn))
    return game
