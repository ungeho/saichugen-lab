"""共通配札・役割別乱数でRollout設定を比較する小規模実験。"""
from collections import defaultdict
from dataclasses import asdict, replace
from hashlib import sha256
from itertools import permutations
from pathlib import Path
from random import Random
from time import perf_counter_ns, monotonic
import json
import os
import platform
import subprocess

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from .runner import _play_game, derived_seed
from ..game.engine import Game
from ..game.rules import RULE_VERSION
from ..game.rewards import REWARD_VERSION, terminal_rewards
from ..strategies.base import Decision
from ..strategies.baselines import NAMES, Baseline
from ..strategies.monte_carlo import MonteCarloRollout

BASELINE_COMMIT = "8b380bec5e85f6368f7aa2f1c49db818f3abb160"
KIND = "rollout_quality_v1"
ROTATIONS = tuple(permutations(range(3)))


class Setting(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trials: int = Field(strict=True, ge=1, le=64)
    continuation: str = "Random"
    time_limit_ms: float | None = Field(default=None, strict=True, ge=0, le=5000, allow_inf_nan=False)

    @field_validator("continuation")
    @classmethod
    def lightweight(cls, value):
        if value not in NAMES:
            raise ValueError("継続戦略は既存5戦略に限定します")
        return value

    @property
    def identifier(self):
        return f"{self.trials}/{self.continuation}/{self.time_limit_ms}"


class StudyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseline_commit: str = BASELINE_COMMIT
    name: str = Field(default="Rollout探索品質", max_length=100)
    deal_seeds: list[StrictInt] = Field(default_factory=lambda: [0], min_length=1, max_length=20)
    policy_seed: int = Field(default=42, strict=True, ge=-9007199254740991, le=9007199254740991)
    opponents: tuple[str, str] = ("Random", "Heuristic")
    settings: list[Setting] = Field(min_length=1, max_length=8)
    analyze_position: bool = True
    timeout_seconds: int = Field(default=300, strict=True, ge=1, le=300)

    @model_validator(mode="after")
    def safe_plan(self):
        if self.baseline_commit != BASELINE_COMMIT:
            raise ValueError("Phase 16の確定SHAと一致しません")
        if len(set(self.deal_seeds)) != len(self.deal_seeds) or any(not 0 <= s <= 9007199254740991 for s in self.deal_seeds):
            # Python Randomの整数seedは符号で同じ配札になり得るため非負に限定。
            raise ValueError("配札seedは重複のない非負の安全な整数にしてください")
        if any(n not in NAMES for n in self.opponents):
            raise ValueError("相手は既存5戦略から選んでください")
        if len({s.identifier for s in self.settings}) != len(self.settings):
            raise ValueError("重複した設定です")
        if estimate(self)["games"] > 360 or estimate(self)["rollout_upper_bound"] > 500000:
            raise ValueError("最大360対局・概算50万Rollout以内で段階実行してください")
        return self


def estimate(config):
    games = len(config.deal_seeds) * 6 * len(config.settings)
    # 17+16+...+3=150候補/対局。プローブは5候補×設定試行数。
    return {"games": games, "independent_deals": len(config.deal_seeds), "rotations": 6,
            "rollout_upper_bound": 6*len(config.deal_seeds)*150*sum(s.trials for s in config.settings)
                + (5*sum(s.trials for s in config.settings) if config.analyze_position else 0),
            "note": "候補数×試行数の上限見積もり。継続戦略・残りターンで処理時間は変わります。"}


def presets():
    directory = Path(__file__).resolve().parents[4] / "experiments" / "presets"
    return [{"id": p.stem, "config": StudyConfig.model_validate_json(p.read_text(encoding="utf-8")).model_dump()}
            for p in sorted(directory.glob("rollout-*.json"))]


def runtime_info():
    root = Path(__file__).resolve().parents[4]
    source = Path(__file__).resolve().parents[1]
    def git(*args):
        try:
            return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL).decode().strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    return {"head_commit": git("rev-parse", "HEAD"), "working_tree_dirty": bool(git("status", "--porcelain")),
            "python": platform.python_version(), "cpu": os.environ.get("PROCESSOR_IDENTIFIER", platform.processor()),
            "source_sha256": {p.relative_to(source).as_posix(): sha256(p.read_bytes()).hexdigest()
                              for p in sorted(source.rglob("*.py"))}}


class MeasuredRollout:
    """詳細を即座に破棄して、計算量と時間だけを記録する。"""
    name = "monte_carlo_rollout"
    version = "1"

    def __init__(self, setting):
        self.strategy = MonteCarloRollout(**setting.model_dump())
        self.samples = []

    def choose(self, observation, rng):
        start = perf_counter_ns()
        decision = self.strategy.choose_detailed(observation, rng)
        elapsed = perf_counter_ns() - start
        meta = decision.details.optional_metadata
        self.samples.append({"elapsed_ns": elapsed, "started_rollouts": meta["started_games"],
                             "executed_rollouts": meta["executed_games"], "accepted_rollouts": meta["completed_games"],
                             "timed_out": meta["timed_out"]})
        return replace(decision, details=None)


def probe(config, check):
    game = Game(config.deal_seeds[0])
    for _ in range(12):
        game.play(tuple(game.observe(p).legal_actions[0] for p in range(3)))
    observation = game.observe(0)
    serialized = asdict(observation)
    snapshot = sha256(json.dumps(serialized, sort_keys=True).encode()).hexdigest()
    seed = derived_seed(config.policy_seed, "quality-probe:0")
    choices = []
    for setting in config.settings:
        check()
        decision = MonteCarloRollout(**setting.model_dump()).choose_detailed(observation, Random(seed))
        check()
        choices.append({"setting": setting.identifier, "parameters": setting.model_dump(),
                        "selected_card": asdict(decision.card), "candidates": [asdict(c) for c in decision.details.candidates],
                        "seed": decision.details.optional_metadata["seed"]})
    return {"snapshot_id": snapshot, "observation": serialized, "choices": choices,
            "changed": len({json.dumps(c["selected_card"], sort_keys=True) for c in choices}) > 1,
            "generation": "最初の配札で全席が先頭合法札を12回出した共通局面。実対戦の局面ではありません。"}


def run_study(config, on_row=lambda row: None, check=lambda: None, on_partial=lambda row: None):
    """同じroleの初期乱数を設定間で共有。元の対局やregistryは変更しない。"""
    for deal in config.deal_seeds:
        for rotation, roles in enumerate(ROTATIONS):
            for setting in config.settings:
                check()
                target = MeasuredRollout(setting)
                instances = [target if role == 0 else Baseline(config.opponents[role-1]) for role in roles]
                names = tuple(s.name for s in instances)
                rngs = [Random(derived_seed(config.policy_seed, f"quality-policy:{deal}:{role}")) for role in roles]
                started = perf_counter_ns()
                try:
                    game, _, _ = _play_game(deal, names, False, False, strategies=instances, rngs=rngs, check=check)
                except Exception:
                    on_partial({"setting": setting.identifier, "deal_id": str(deal), "rotation": rotation,
                                "game_elapsed_ns": perf_counter_ns()-started, "decisions": target.samples})
                    raise
                elapsed = perf_counter_ns() - started
                seat = roles.index(0)
                row = {"deal_id": str(deal), "seed": deal, "rotation": rotation, "roles": roles,
                       "strategies": names, "seat": seat, "setting": setting.identifier,
                       "rollout_parameters": setting.model_dump(), "strategy_version": target.version,
                       "scores": game.observe(0).game_scores, "winners": game.winners,
                       "terminal_rewards": terminal_rewards(game.winners), "game_elapsed_ns": elapsed,
                       "decisions": target.samples}
                on_row(row)


def interval(values, seed):
    """配札平均（または対応差）を単位とした百分位ブートストラップ。"""
    if len(values) < 2:
        return None
    rng = np.random.default_rng(seed)
    samples = rng.choice(values, size=(2000, len(values)), replace=True).mean(axis=1)
    return [float(x) for x in np.quantile(samples, [.025, .975])]


def summarize_study(config, rows, partial_games=()):
    groups = defaultdict(lambda: defaultdict(list))
    for row in rows:
        groups[row["setting"]][row["deal_id"]].append(row)
    summaries = []
    clusters = {}
    for setting in config.settings:
        recorded = [r for rs in groups[setting.identifier].values() for r in rs]
        costs = recorded + [r for r in partial_games if r["setting"] == setting.identifier]
        complete = {deal: rs for deal, rs in groups[setting.identifier].items()
                    if len(rs) == 6 and {r["rotation"] for r in rs} == set(range(6))}
        used = [r for rs in complete.values() for r in rs]
        means = {deal: float(np.mean([r["terminal_rewards"][r["seat"]] for r in rs])) for deal,rs in complete.items()}
        clusters[setting.identifier] = means
        timings = [d["elapsed_ns"]/1e6 for r in costs for d in r["decisions"]]
        mean = lambda seq: float(np.mean(seq)) if seq else None
        summaries.append({"setting": setting.identifier, "parameters": setting.model_dump(),
            "games": len(used), "recorded_games": len(recorded), "excluded_partial_games": len(recorded)-len(used),
            "independent_deals": len(complete), "average_terminal_reward": mean(list(means.values())),
            "reward_ci95": interval(list(means.values()), config.policy_seed % (2**32)),
            "sole_win_rate": mean([int(len(r["winners"]) == 1 and r["seat"] in r["winners"]) for r in used]),
            "joint_win_rate": mean([int(r["seat"] in r["winners"] and len(r["winners"])>1) for r in used]),
            "average_score": mean([r["scores"][r["seat"]] for r in used]),
            "decision_ms": {"mean": mean(timings), "median": float(np.median(timings)) if timings else None,
                            "p95": float(np.quantile(timings,.95)) if timings else None, "max": max(timings) if timings else None},
            "game_seconds_mean": mean([r["game_elapsed_ns"]/1e9 for r in recorded]),
            "incomplete_games": len(costs)-len(recorded),
            "started_rollouts": sum(d["started_rollouts"] for r in costs for d in r["decisions"]),
            "executed_rollouts": sum(d["executed_rollouts"] for r in costs for d in r["decisions"]),
            "accepted_rollouts": sum(d["accepted_rollouts"] for r in costs for d in r["decisions"]),
            "timeout_decisions": sum(d["timed_out"] for r in costs for d in r["decisions"])})
    baseline = config.settings[0].identifier
    differences = []
    for setting in config.settings[1:]:
        common = sorted(clusters[baseline].keys() & clusters[setting.identifier].keys())
        values = [clusters[setting.identifier][d]-clusters[baseline][d] for d in common]
        differences.append({"setting": setting.identifier, "baseline": baseline, "independent_deals": len(common),
                            "difference": float(np.mean(values)) if values else None,
                            "ci95": interval(values, config.policy_seed % (2**32))})
    return {"settings": summaries, "differences": differences, "baseline": baseline,
            "method": "各設定で6席順が揃った配札の平均を1標本とする2000回百分位ブートストラップ。差は共通配札の対応差。",
            "warning": "独立配札が少ない場合は不安定。1配札では区間未提供。分散0でも確実性を保証しません。"}
