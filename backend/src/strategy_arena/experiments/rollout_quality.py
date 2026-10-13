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
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from .runner import _play_game, derived_seed
from ..game.engine import Game
from ..game.rules import RULE_VERSION
from ..game.rewards import REWARD_VERSION, terminal_rewards
from ..strategies.base import Decision
from ..strategies.baselines import NAMES, Baseline
from ..strategies.monte_carlo import MonteCarloRollout
from ..strategies.hybrid import HybridSearch, METHOD_NAMES
from ..strategies.theory_policy import TheoryPolicy, TheorySearch
from ..strategies.theories import TheoryConfig

BASELINE_COMMIT = "e12a27e40233e13a2d5faaae8776bb3e790359d5"
PHASE18_BASELINE = "0216601af12936805af91a8dccf11a45c5d36f1d"
PHASE17_BASELINE = "600be06469e789395257d00afdbc11d039369869"
LEGACY_BASELINE = "8b380bec5e85f6368f7aa2f1c49db818f3abb160"
KIND = "rollout_quality_v1"
ROTATIONS = tuple(permutations(range(3)))


class Setting(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trials: int = Field(default=8, strict=True, ge=1, le=64)
    method: Literal["legacy","uniform","heuristic","adaptive","combined","theory","baseline","theory_search","theory_search_adaptive"] = "legacy"
    theory_config: TheoryConfig | None = None
    baseline_name: str | None = None
    total_budget: int | None = Field(default=None, strict=True, ge=1, le=1024)
    min_trials: int = Field(default=1, strict=True, ge=1, le=8)
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
        if self.method=='baseline':return 'baseline/'+self.baseline_name
        if self.method.startswith('theory'):
            key=sha256(json.dumps(self.theory_config.model_dump(),sort_keys=True).encode()).hexdigest()[:16]
            return f"{self.method}/{key}/{self.total_budget}/{self.continuation}/{self.time_limit_ms}/min{self.min_trials}"
        if self.method != "legacy":
            return f"{self.method}/{self.total_budget}/{self.continuation}/{self.time_limit_ms}/min{self.min_trials}"
        return f"{self.trials}/{self.continuation}/{self.time_limit_ms}"

    @model_validator(mode="after")
    def budget_mode(self):
        if (self.method in ("legacy","theory","baseline")) != (self.total_budget is None):
            raise ValueError("総予算方式にはtotal_budgetが必須。従来方式には指定できません")
        if self.method=="legacy" and self.min_trials!=1:
            raise ValueError("従来方式はmin_trials設定に非対応です")
        if self.method!="legacy" and self.trials!=8:
            raise ValueError("総予算方式に候補あたりtrialsは適用しません。既定8のままにしてください")
        if self.method.startswith('theory') != (self.theory_config is not None):
            raise ValueError("Theory方式にだけtheory_configが必要です")
        if (self.method=='baseline') != (self.baseline_name is not None) or (self.baseline_name is not None and self.baseline_name not in NAMES):
            raise ValueError("baseline方式に既存5戦略名を指定してください")
        if self.method in ('theory','baseline') and (self.time_limit_ms is not None or self.min_trials!=1):
            raise ValueError("直接評価には探索時間上限・最低試行を指定できません")
        if self.method in ('theory','baseline') and self.continuation!='Random':
            raise ValueError("直接評価は継続戦略を使いません。既定Randomのままにしてください")
        return self

    @property
    def strategy_name(self):
        if self.method=='baseline':return self.baseline_name
        if self.method.startswith('theory'):return 'theory_policy' if self.method=='theory' else self.method
        return "monte_carlo_rollout" if self.method=="legacy" else METHOD_NAMES[self.method]

    @property
    def budget_family(self):
        return 'direct' if self.method in ('theory','baseline') else 'legacy' if self.method=='legacy' else 'budget'

    @property
    def rollout_bound(self):
        return 0 if self.budget_family=='direct' else 150*self.trials if self.method=='legacy' else 15*self.total_budget

    def create_strategy(self):
        if self.method=='baseline':return Baseline(self.baseline_name)
        if self.method=='theory':return TheoryPolicy(self.theory_config)
        if self.method.startswith('theory_search'):
            return TheorySearch(self.theory_config,self.method.endswith('adaptive'),self.total_budget,self.continuation,
                                time_limit_ms=self.time_limit_ms,min_trials=self.min_trials)
        if self.method=="legacy":
            return MonteCarloRollout(self.trials,self.continuation,time_limit_ms=self.time_limit_ms)
        return HybridSearch(self.method,self.total_budget,self.continuation,
                            time_limit_ms=self.time_limit_ms,min_trials=self.min_trials)


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
    seed_partition: Literal['unassigned','development','validation','final'] = 'unassigned'

    @model_validator(mode="after")
    def safe_plan(self):
        if self.baseline_commit not in (BASELINE_COMMIT, PHASE18_BASELINE, PHASE17_BASELINE, LEGACY_BASELINE):
            raise ValueError("既知の確定基準SHAと一致しません")
        if len(set(self.deal_seeds)) != len(self.deal_seeds) or any(not 0 <= s <= 9007199254740991 for s in self.deal_seeds):
            # Python Randomの整数seedは符号で同じ配札になり得るため非負に限定。
            raise ValueError("配札seedは重複のない非負の安全な整数にしてください")
        if any(n not in NAMES for n in self.opponents):
            raise ValueError("相手は既存5戦略から選んでください")
        if len({s.identifier for s in self.settings}) != len(self.settings):
            raise ValueError("重複した設定です")
        if estimate(self)["games"] > 360 or estimate(self)["rollout_upper_bound"] > 500000:
            raise ValueError("最大360対局・概算50万Rollout以内で段階実行してください")
        modes={s.budget_family for s in self.settings}
        if len(modes)>1:
            raise ValueError("候補あたり試行数と総予算方式は同一実験に混在できません")
        if 'budget' in modes and len({(s.total_budget,s.min_trials,s.continuation,s.time_limit_ms) for s in self.settings})!=1:
            raise ValueError("総予算の方式比較では予算・最低試行・継続戦略・時間上限を揃えてください")
        starts={'development':0,'validation':1000000,'final':2000000}
        if any(s.method.startswith('theory') for s in self.settings) and self.seed_partition=='unassigned':
            raise ValueError("Theory実験には開発・検証・最終評価のseed用途を指定してください")
        if self.seed_partition!='unassigned' and any(not starts[self.seed_partition]<=s<starts[self.seed_partition]+1000000 for s in self.deal_seeds):
            raise ValueError("seedが用途別の非重複区分範囲にありません")
        return self


def estimate(config, historical=()):
    from .quality_planning import resource_plan
    games = len(config.deal_seeds) * 6 * len(config.settings)
    # 17+16+...+3=150候補/対局。プローブは5候補×設定試行数。
    return {"games": games, "independent_deals": len(config.deal_seeds), "rotations": 6,
            "settings_count":len(config.settings), **resource_plan(config,historical),
            "rollout_upper_bound": 6*len(config.deal_seeds)*sum(s.rollout_bound for s in config.settings)
                + (sum(5*s.trials if s.method=="legacy" else s.total_budget or 0 for s in config.settings) if config.analyze_position else 0),
            "note": "候補数×試行数の上限見積もり。継続戦略・残りターンで処理時間は変わります。"}


def presets():
    directory = Path(__file__).resolve().parents[4] / "experiments" / "presets"
    return [{"id": p.stem, "config": StudyConfig.model_validate_json(p.read_text(encoding="utf-8")).model_dump()}
            for p in sorted(directory.glob("rollout-*.json"), key=lambda p:(-1 if "phase19" in p.stem else 0 if p.stem=="rollout-phase18-stage1-random" else 1 if "phase18-stage1" in p.stem else 3 if "phase18-stage2" in p.stem else 2,p.stem))]


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
        self.strategy = setting.create_strategy()
        self.setting = setting
        self.name, self.version = self.strategy.name, self.strategy.version
        self.samples = []

    def choose(self, observation, rng):
        start = perf_counter_ns()
        decision = self.strategy.choose_detailed(observation, rng)
        elapsed = perf_counter_ns() - start
        meta = decision.details.optional_metadata or {}
        self.samples.append({"elapsed_ns": elapsed, "started_rollouts": meta.get("started_games",0),
                             "executed_rollouts": meta.get("executed_games",0), "accepted_rollouts": meta.get("completed_games",0),
                             "timed_out": meta.get("timed_out",False),
                             "total_budget":meta.get("total_budget"),"unused_budget":meta.get("unused_budget"),
                             "heuristic_ns":int(meta.get("heuristic_ms",0)*1e6),"allocation_ns":int(meta.get("allocation_ms",0)*1e6),
                             **({'turn':observation.turn,'round':observation.turn//3+1,
                                 'phase':'early' if observation.turn<5 else 'middle' if observation.turn<10 else 'late',
                                 'selected_rank':decision.card.rank,'strong_count':sum(c.rank>=10 for c in observation.hand),
                                 'middle_count':sum(5<=c.rank<=9 for c in observation.hand),
                                 'hand_group':'strong_rich' if sum(c.rank>=10 for c in observation.hand)>=len(observation.hand)/2 else 'other'} if self.setting.method.startswith('theory') else {})})
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
        decision = setting.create_strategy().choose_detailed(observation, Random(seed))
        check()
        choices.append({"setting": setting.identifier, "parameters": setting.model_dump(),
                        "selected_card": asdict(decision.card), "candidates": [asdict(c) for c in decision.details.candidates],
                        "seed": (decision.details.optional_metadata or {}).get("seed",str(seed)),
                        **({"search_metadata":decision.details.optional_metadata} if setting.method!="legacy" else {})})
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
    from .quality_statistics import complete_deals, paired_clusters, uncertainty
    summaries = []
    clusters = {}
    for setting in config.settings:
        recorded = [r for rs in groups[setting.identifier].values() for r in rs]
        costs = recorded + [r for r in partial_games if r["setting"] == setting.identifier]
        complete = complete_deals(config, rows, setting)
        used = [r for rs in complete.values() for r in rs]
        means = {deal: float(np.mean([r["terminal_rewards"][r["seat"]] for r in rs])) for deal,rs in complete.items()}
        clusters[setting.identifier] = complete
        info = uncertainty(list(means.values()), config.policy_seed)
        timings = [d["elapsed_ns"]/1e6 for r in costs for d in r["decisions"]]
        mean = lambda seq: float(np.mean(seq)) if seq else None
        summaries.append({"setting": setting.identifier, "parameters": setting.model_dump(mode='json'),
            "games": len(used), "recorded_games": len(recorded), "excluded_partial_games": len(recorded)-len(used),
            "independent_deals": len(complete), "average_terminal_reward": mean(list(means.values())),
            "reward_ci95": info["ci95"], "uncertainty": info,
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
        summaries[-1].update({"heuristic_ms_mean":mean([d.get("heuristic_ns",0)/1e6 for r in costs for d in r["decisions"]]),
            "allocation_ms_mean":mean([d.get("allocation_ns",0)/1e6 for r in costs for d in r["decisions"]]),
            "unused_budget":sum(d.get("unused_budget") or 0 for r in costs for d in r["decisions"])})
        trends=[]
        for dimension in ('phase','round','hand_group'):
            samples=defaultdict(list)
            for r in costs:
                for d in r['decisions']:
                    if dimension in d:samples[str(d[dimension])].append(d['selected_rank'])
            trends.extend({'dimension':dimension,'group':key,'decisions':len(values),'mean_selected_rank':mean(values)} for key,values in sorted(samples.items()))
        summaries[-1]['decision_trends']=trends
    baseline = config.settings[0].identifier
    differences = []
    for setting in config.settings[1:]:
        comparison = paired_clusters(clusters[baseline], clusters[setting.identifier], config.settings[0], setting, config.policy_seed)
        differences.append({"setting": setting.identifier, "baseline": baseline, **comparison})
    return {"settings": summaries, "differences": differences, "baseline": baseline,
            "method": "各設定で6席順が揃った配札の平均を1標本とする2000回百分位ブートストラップ。差は共通配札の対応差。",
            "warning": "独立配札が少ない場合は不安定。10配札未満・標本分散0では区間非表示。10〜19配札も参考値です。"}
