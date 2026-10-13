"""終局指標の集計と旧JSONの読み取り時補完。保存データを書き換えない。"""
from collections import Counter, defaultdict
from copy import deepcopy
from math import isfinite
from ..game.rules import RULE_VERSION
from ..game.rewards import REWARD_VERSION, terminal_rewards


def evaluated_result(row, rule_version=RULE_VERSION, reward_version=None):
    result = dict(row)
    try:
        expected = terminal_rewards(row.get("winners"))
    except ValueError:
        expected = None
    version = row.get("reward_version", reward_version)
    source = "unknown"
    rewards = None
    if expected is not None and version in (None, REWARD_VERSION):
        if "terminal_rewards" in row:
            recorded = row["terminal_rewards"]
            if (version == REWARD_VERSION and isinstance(recorded, (list, tuple))
                    and all(type(v) is int for v in recorded) and tuple(recorded) == expected):
                rewards = expected
                source = row.get("reward_source", "recorded")
                if source not in ("recorded", "derived_from_winners"):
                    source = "recorded"
        elif rule_version == RULE_VERSION or version == REWARD_VERSION:
            rewards = expected
            source = "derived_from_winners"
    result.update(terminal_rewards=rewards, reward_source=source,
                  reward_version=REWARD_VERSION if rewards is not None else version)
    return result


def evaluation_metrics(samples, rule_version=RULE_VERSION):
    """samplesは(row, seat)。同名戦略の複数席も別の参加として数える。"""
    sources = Counter()
    rewards = []
    sole = joint = known = 0
    scores = []
    for row, p in samples:
        result = evaluated_result(row, rule_version)
        sources[result["reward_source"]] += 1
        if result["terminal_rewards"] is not None:
            rewards.append(result["terminal_rewards"][p])
        try:
            terminal_rewards(row.get("winners"))
        except ValueError:
            pass
        else:
            known += 1
            if p in row["winners"]:
                sole += len(row["winners"]) == 1
                joint += len(row["winners"]) > 1
        values = row.get("scores")
        if isinstance(values, (list, tuple)) and len(values) == 3 and all(type(v) in (int, float) and isfinite(v) for v in values):
            scores.append(values[p])
    count = len(samples)
    return {"sole_wins": sole, "joint_wins": joint, "outcome_games": known,
            "sole_win_rate": sole / count if count and known == count else None,
            "joint_win_rate": joint / count if count and known == count else None,
            "average_score": sum(scores) / len(scores) if scores else None,
            "average_terminal_reward": sum(rewards) / len(rewards) if rewards else None,
            "reward_games": len(rewards), "reward_unknown_games": count - len(rewards),
            "reward_sources": dict(sources), "reward_version": REWARD_VERSION if rewards else None}


def enrich_payload(payload):
    """旧結果にも新指標を追加する読み取りアダプター。累計・ルール版を維持。"""
    result = deepcopy(payload)
    rule = payload.get("rule_version")
    rows = [evaluated_result(row, rule, payload.get("reward_version")) for row in payload.get("results", [])]
    result["results"] = rows
    sources = Counter(row["reward_source"] for row in rows)
    result["reward_compatibility"] = {"recorded_games": sources["recorded"],
                                    "derived_games": sources["derived_from_winners"],
                                    "unknown_games": sources["unknown"],
                                    "note": "旧結果は勝者情報から読み取り時に補完。元データ・累計得点・ルール版は変更しません。"}
    by_name = defaultdict(list)
    for row in rows:
        for p, name in enumerate(row.get("strategies", ())):
            if p < 3:
                by_name[name].append((row, p))
    summary = result.setdefault("summary", {}).setdefault("strategies", {})
    for name, samples in by_name.items():
        summary.setdefault(name, {}).update(evaluation_metrics(samples, rule))
    return result

