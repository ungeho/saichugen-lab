from collections import defaultdict
from math import sqrt

import numpy as np


def wilson(wins: int, count: int) -> tuple[float, float]:
    if not count:
        return (0.0, 1.0)
    z = 1.959963984540054
    p = wins / count
    denominator = 1 + z * z / count
    center = (p + z * z / (2 * count)) / denominator
    half = z * sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    return max(0, center - half), min(1, center + half)


def summarize(results: list[dict]) -> dict:
    rows = defaultdict(list)
    for game in results:
        for p, name in enumerate(game["strategies"]):
            rows[name].append({"seed": game["seed"], "seat": p,
                               "win": int(p in game["winners"]),
                               "score": game["scores"][p], "turns": game["turn_wins"][p],
                               "elapsed": game["elapsed_ns"][p]})
    summary = {}
    for name, samples in rows.items():
        clusters = defaultdict(list)
        for row in samples:
            clusters[row["seed"]].append(row["win"])
        means = np.array([np.mean(values) for values in clusters.values()])
        # 座席回転の試合は独立でないため、配札シードを単位に再標本化する。
        ci = None
        if len(means) >= 2:
            rng = np.random.default_rng(20261013)
            boot = np.array([rng.choice(means, size=len(means), replace=True).mean() for _ in range(1000)])
            ci = [float(x) for x in np.quantile(boot, [0.025, 0.975])]
        summary[name] = {
            "games": len(samples), "wins": sum(r["win"] for r in samples),
            "win_rate": float(np.mean([r["win"] for r in samples])),
            "ci95": ci, "independent_deals": len(means),
            "turn_win_rate": sum(r["turns"] for r in samples) / (15 * len(samples)),
            "scores": [r["score"] for r in samples],
            "recent_win_rate": float(np.mean([r["win"] for r in samples[-100:]])),
            "mean_decision_ms": float(np.mean([r["elapsed"] for r in samples])) / 15e6,
            "seat_win_rates": [float(np.mean([r["win"] for r in samples if r["seat"] == seat]))
                               if any(r["seat"] == seat for r in samples) else None for seat in range(3)],
            "cumulative_win_rates": (np.cumsum([r["win"] for r in samples]) / np.arange(1, len(samples) + 1)).tolist(),
        }
    return {"strategies": summary, "games": len(results),
            "confidence_method": "配札シード単位のパーセンタイル・ブートストラップ（1000回）",
            "win_definition": "中央値と同点の各プレイヤーを1勝として集計。勝率の合計は100%を超えうる。"}
