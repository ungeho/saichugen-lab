"""推論の評価は完全情報側にのみ配置する。対戦APIには公開しない。"""

from ..game.engine import Game


def membership_brier(game: Game, observer: int, opponent: int, probabilities: dict) -> float:
    """未知札それぞれが相手の手札にある確率の平均二乗誤差。"""
    if opponent not in range(3) or observer == opponent:
        raise ValueError("別のプレイヤーを指定してください")
    pool = game.observe(observer).unseen_cards
    if set(probabilities) != set(pool):
        raise ValueError("未知札すべての確率が必要")
    if any(not 0 <= value <= 1 for value in probabilities.values()):
        raise ValueError("確率は0〜1")
    actual = set(game._hands[opponent])
    return sum((probabilities[c] - int(c in actual)) ** 2 for c in pool) / len(pool)
