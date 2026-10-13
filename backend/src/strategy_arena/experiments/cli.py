"""例: python -m strategy_arena.experiments.cli --deals 100 --output results.json"""

import argparse
import json
from pathlib import Path
from time import perf_counter

from .runner import run_experiment
from .metrics import summarize
from ..game.rules import RULE_VERSION
from ..strategies.registry import create_strategy, strategy_names


def main():
    parser = argparse.ArgumentParser(description="最中限の対戦実験")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--deals", type=int, default=100)
    parser.add_argument("--strategies", nargs=3, choices=strategy_names(), default=["Random", "Greedy", "Heuristic"])
    parser.add_argument("--output", type=Path, default=Path("results.json"))
    parser.add_argument("--capture-details", action="store_true", help="判断の詳細を保存（大量対戦では省略を推奨）")
    args = parser.parse_args()
    if args.deals < 1:
        parser.error("配札数は1以上")
    start = perf_counter()
    results = run_experiment(list(range(args.seed, args.seed + args.deals)), tuple(args.strategies), capture_details=args.capture_details)
    payload = {"rule_version": RULE_VERSION, "information_condition": "imperfect",
               "config": {"seed": args.seed, "deals": args.deals, "strategies": args.strategies, "rotate": True, "capture_details": args.capture_details},
               "strategy_parameters": {},
               "strategy_versions": {name: create_strategy(name).version for name in args.strategies},
               "results": results, "summary": summarize(results)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    elapsed = perf_counter() - start
    print(f"{len(results)}試合 / {elapsed:.2f}秒 / {len(results)/elapsed:.1f}試合/秒")
    for name, metric in payload["summary"]["strategies"].items():
        print(f"{name}: 勝率 {metric['win_rate']:.1%}, ターン獲得率 {metric['turn_win_rate']:.1%}")


if __name__ == "__main__":
    main()
