"""対戦を進めず、同じ不完全情報の観測で戦略を比較する。"""

from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
from random import Random
from time import perf_counter_ns

from .experiments.runner import derived_seed
from .game.cards import Card
from .game.rules import RULE_VERSION
from .research.replay import export_full, replay
from .strategies.base import decide, decision_record
from .strategies.registry import create_strategy


class ComparisonUnavailable(ValueError):
    pass


def clone_strategy(strategy):
    """モデル・内部状態を維持する。特殊なモデルは任意の複製メソッドを提供できる。"""
    try:
        custom = getattr(strategy, "clone_for_comparison", None)
        clone = custom() if callable(custom) else deepcopy(strategy)
        if clone is strategy:
            raise ValueError("同一インスタンス")
        return clone
    except Exception as error:
        raise ComparisonUnavailable(
            f"内部状態を独立に複製できません（{type(error).__name__}）。clone_for_comparisonの実装を確認してください。"
        ) from error


def initial_strategy_copies(strategies):
    copies = []
    for strategy in strategies:
        try:
            copies.append(clone_strategy(strategy))
        except ComparisonUnavailable:
            # 比較への対応不足で通常のゲームを開始できなくしない。
            copies.append(None)
    return copies


def position_at(game, turn: int | None, player: int):
    current = game.observe(player).turn
    turn = current if turn is None else turn
    if not 0 <= turn < 15 or turn > current:
        raise ValueError("まだ到達していない局面、または終了後の局面です。履歴のターン1〜15の選択直前を指定してください。")
    full = export_full(game)
    full["actions"] = full["actions"][:turn]
    # 既存のリプレイ検証を使う。完全情報は複製したエンジン内でのみ扱う。
    observation = replay(full).observe(player)
    snapshot = {"schema_version": 1, "rule_version": RULE_VERSION,
                "information_condition": "imperfect", "observation": asdict(observation)}
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return observation, {**snapshot, "snapshot_id": sha256(canonical.encode()).hexdigest(),
                         "legal_actions": [asdict(card) for card in observation.legal_actions]}


def comparison_strategy(session, name: str, turn: int, player: int):
    if name != session["names"][player]:
        return clone_strategy(create_strategy(name)), "registered_initial_copy", "登録設定から作った初期状態を複製（学習済み値があれば保持）"
    if turn == session["game"].observe(player).turn:
        return clone_strategy(session["strategies"][player]), "live_copy", "この席の対戦中の内部状態を複製"
    initial = session["comparison_initial_strategies"][player]
    if initial is None:
        raise ComparisonUnavailable("初期の内部状態を保存できなかったため、この戦略の過去局面は復元できません。")
    strategy = clone_strategy(initial)
    rng = Random()
    rng.setstate(session["initial_rng_states"][player])
    full = export_full(session["game"])
    actions = full["actions"][:turn]
    full["actions"] = []
    historical = replay(full)
    for index, cards in enumerate(actions):
        actual = tuple(Card(*card) for card in cards)
        # 人間が操作したP1では、通常対戦でも戦略chooseを呼んでいない。
        if not (player == 0 and session["human_turns"][index]):
            decision = decide(strategy, historical.observe(player), rng, session["capture_details"])
            if decision.card != actual[player]:
                raise ComparisonUnavailable("履歴再実行の選択が実際の記録と一致しません。この戦略の過去の内部状態は再現できません。")
        historical.play(actual)
    return strategy, "history_reconstructed", "保存した初期状態と実際の履歴から、この席の当時の状態を復元"


def compare_position(session, names: list[str], seed: int, turn: int | None = None, player: int = 0) -> dict:
    observation, position = position_at(session["game"], turn, player)
    results = []
    for name in names:
        result = {"name": name, "status": "error", "version": None, "decision": None,
                  "state_source": None, "state_note": "", "elapsed_ns": None, "derived_seed": None}
        try:
            strategy, source, note = comparison_strategy(session, name, observation.turn, player)
            result.update(version=strategy.version, state_source=source, state_note=note)
            independent_seed = derived_seed(seed, f"position-comparison:{name}:{strategy.version}")
            result["derived_seed"] = str(independent_seed)
            rng = Random(independent_seed)
            start = perf_counter_ns()
            try:
                decision = decide(strategy, observation, rng, capture_details=True)
            finally:
                result["elapsed_ns"] = perf_counter_ns() - start
            if decision.card not in observation.legal_actions:
                raise ComparisonUnavailable("合法手ではないカードを返したため、比較結果として採用できません。")
            result.update(status="ok", decision=decision_record(decision, observation, True))
        except ComparisonUnavailable as error:
            result["error"] = str(error)
        except Exception as error:
            result["error"] = f"比較用の実行に失敗しました（{type(error).__name__}）。他の戦略の結果は表示できます。"
        results.append(result)
    return {"position": position, "seed": seed, "results": results,
            "randomness_note": "戦略名・バージョンごとに独立した乱数源を使用。判断時間は再現性の対象外です。"}
