"""2003年論文表2の終局報酬。累計得点・勝者判定とは独立。"""
from collections.abc import Iterable, Mapping

REWARD_VERSION = "saichugen-2003-table2-v1"

def terminal_rewards(winners: Iterable[int]) -> tuple[int, int, int]:
    """確定した非空の勝者集合から、座席0,1,2順のゼロ和報酬を返す。"""
    if isinstance(winners, (str, bytes, Mapping)):
        raise ValueError("勝者は重複のない座席番号集合で指定してください")
    try:
        seats = tuple(winners)
    except TypeError as error:
        raise ValueError("勝者集合が必要です") from error
    if not 1 <= len(seats) <= 3 or any(type(p) is not int or p not in range(3) for p in seats):
        raise ValueError("勝者は0〜2の座席番号で、1〜3人必要です")
    if len(set(seats)) != len(seats):
        raise ValueError("勝者の重複は許可されません")
    count = len(seats)
    reward = (2, 1, 0)[count - 1]
    penalty = (-1, -2, 0)[count - 1]
    return tuple(reward if p in seats else penalty for p in range(3))

