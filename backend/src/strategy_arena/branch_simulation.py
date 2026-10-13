"""観測だけから共通の世界を生成する分岐実験。"""
from collections import Counter
from dataclasses import asdict
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4
import math
from .experiments.metrics import wilson
from .game.rewards import REWARD_VERSION
from .rollouts import sampled_game, rollout_trial
from .strategies.registry import create_strategy

def aggregate(card, outcomes):
    scores = [row["score"] for row in outcomes]
    count = len(scores)
    wins = sum(row["win"] for row in outcomes)
    mean = sum(scores) / count
    rewards = [row["reward"] for row in outcomes if "reward" in row]
    complete = all("sole_win" in row and "joint_win" in row for row in outcomes)
    return {"card": asdict(card), "trials": count, "wins": wins, "win_rate": wins / count,
            "sole_win_rate": sum(row["sole_win"] for row in outcomes) / count if complete else None,
            "joint_win_rate": sum(row["joint_win"] for row in outcomes) / count if complete else None,
            "average_terminal_reward": sum(rewards) / len(rewards) if rewards else None,
            "ci95": wilson(wins, count), "average_score": mean,
            "score_std": math.sqrt(sum((s - mean) ** 2 for s in scores) / count),
            "rank_distribution": dict(Counter(row["rank"] for row in outcomes))}


def paired_reward_statistics(first, second):
    if len(first) != len(second) or not first:
        raise ValueError("対応する非空の報酬標本が必要です")
    differences = [a - b for a, b in zip(first, second)]
    count = len(differences)
    mean = sum(differences) / count
    ci = None
    if count > 1:
        se = math.sqrt(sum((d - mean) ** 2 for d in differences) / (count - 1) / count)
        ci = [max(-4, mean - 1.96 * se), min(4, mean + 1.96 * se)]
    return {"average_terminal_reward_difference": mean, "reward_difference_ci95": ci,
            "reward_difference_samples": count,
            "reward_difference_zero_variance": count > 1 and len(set(differences)) == 1}

def simulate(observation, position, cards, names, trials, seed, check=lambda: None, progress=lambda n: None):
    templates = [create_strategy(name) for name in names]
    versions = [s.version for s in templates]
    outcomes = [[] for _ in cards]
    for trial in range(trials):
        check()
        for index, row in enumerate(rollout_trial(observation, cards, templates, seed, trial, check, names)):
            outcomes[index].append(row)
        progress(trial + 1)
    paired = []
    for i in range(len(cards)):
        for j in range(i + 1, len(cards)):
            differences = [a["win"] - b["win"] for a, b in zip(outcomes[i], outcomes[j])]
            mean = sum(differences) / trials
            se = math.sqrt(sum((d - mean) ** 2 for d in differences) / (trials - 1) / trials) if trials > 1 else None
            paired.append({"a": asdict(cards[i]), "b": asdict(cards[j]), "win_rate_difference": mean,
                           **paired_reward_statistics([r["reward"] for r in outcomes[i]], [r["reward"] for r in outcomes[j]]),
                           "ci95": [max(-1, mean - 1.96 * se), min(1, mean + 1.96 * se)] if se is not None else None,
                           "average_score_difference": sum(a["score"] - b["score"] for a, b in zip(outcomes[i], outcomes[j])) / trials})
    return {"schema_version": 2, "reward_version": REWARD_VERSION, "position": position, "seed": seed, "trials": trials,
            "continuation": [{"name": name, "version": version, **({"parameters": s.parameters} if hasattr(s, "parameters") else {})} for name, version, s in zip(names, versions, templates)],
            "state_policy": "registered_initial_v1", "sampler": "uniform-unseen-v1", "information_condition": "imperfect",
            "sampling_note": "自分の手札と公開履歴を固定し、未公開カードを残り枚数に従って一様に配分。過去の選択傾向による重み付けは行いません。",
            "continuation_note": "全席の継続戦略は登録時の初期状態を複製。対象席の最初の一手だけを強制し、その手番では対象戦略を呼びません。",
            "candidates": [aggregate(card, rows) for card, rows in zip(cards, outcomes)], "paired": paired}

class JobStopped(Exception):
    def __init__(self, status):
        self.status = status

class BranchJobs:
    """単一ワーカー。キャンセル・制限時間は戦略呼び出しの前後で確認。"""
    def __init__(self, timeout=60):
        self.lock = Lock()
        self.jobs = {}
        self.timeout = timeout
        self.closed = False

    def submit(self, observation, position, cards, names, trials, seed):
        cards = tuple(dict.fromkeys(cards))
        if not cards or any(c not in observation.legal_actions for c in cards):
            raise ValueError("候補は合法手から選択してください")
        if type(trials) is not int or not 1 <= trials <= 1000 or trials * len(cards) > 10000:
            raise ValueError("試行回数は1〜1000、候補数×試行回数は10000以下にしてください")
        identifier = str(uuid4())
        with self.lock:
            if self.closed or any(j["status"] in ("running", "cancelling") for j in self.jobs.values()):
                raise RuntimeError("分岐実験は1件ずつ実行してください。実行中の実験を停止するか、完了をお待ちください")
            while len(self.jobs) >= 20:
                del self.jobs[next(iter(self.jobs))]
            job = {"id": identifier, "status": "running", "completed_trials": 0, "total_trials": trials,
                   "candidate_count": len(cards), "result": None, "error": None, "_cancel": Event()}
            self.jobs[identifier] = job
        def worker():
            started = monotonic()
            def check():
                if job["_cancel"].is_set():
                    raise JobStopped("cancelled")
                if monotonic() - started > self.timeout:
                    raise JobStopped("timed_out")
            def progress(n):
                with self.lock:
                    job["completed_trials"] = n
            try:
                result = simulate(observation, position, cards, names, trials, seed, check, progress)
                check()
                with self.lock:
                    job.update(status="completed", result=result)
            except JobStopped as error:
                with self.lock:
                    job["status"] = error.status
            except Exception as error:
                with self.lock:
                    job.update(status="failed", error=f"継続対戦に失敗しました ({type(error).__name__})")
            finally:
                with self.lock:
                    job["elapsed_seconds"] = monotonic() - started
        Thread(target=worker, daemon=True, name="branch-simulation").start()
        return self.get(identifier)

    def get(self, identifier):
        with self.lock:
            return {k: v for k, v in self.jobs[identifier].items() if not k.startswith("_")}

    def cancel(self, identifier):
        with self.lock:
            job = self.jobs[identifier]
            if job["status"] == "running":
                job["_cancel"].set()
                job["status"] = "cancelling"
        return self.get(identifier)

    def close(self):
        with self.lock:
            self.closed = True
            for job in self.jobs.values():
                job["_cancel"].set()

