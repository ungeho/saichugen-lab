"""観測だけから共通の世界を生成する分岐実験。"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from random import Random
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4
import math
from .comparison import clone_strategy
from .experiments.metrics import wilson
from .experiments.runner import derived_seed
from .game.engine import Game
from .inference import UniformSampler
from .strategies.base import decide
from .strategies.registry import create_strategy

def sampled_game(observation, rng):
    hypothesis = UniformSampler().sample(observation, rng)
    hands = [hypothesis.hands[p] + tuple(t.cards[p] for t in observation.history) for p in range(3)]
    game = Game.from_deal(hands, hypothesis.unused)
    for event in observation.history:
        if game.play(event.cards) != event:
            raise ValueError("公開履歴がルールと一致しません")
    if game.observe(observation.player) != observation:
        raise ValueError("復元した観測が一致しません")
    return game

def aggregate(card, outcomes):
    scores = [row["score"] for row in outcomes]
    count = len(scores)
    wins = sum(row["win"] for row in outcomes)
    mean = sum(scores) / count
    return {"card": asdict(card), "trials": count, "wins": wins, "win_rate": wins / count,
            "ci95": wilson(wins, count), "average_score": mean,
            "score_std": math.sqrt(sum((s - mean) ** 2 for s in scores) / count),
            "rank_distribution": dict(Counter(row["rank"] for row in outcomes))}

def simulate(observation, position, cards, names, trials, seed, check=lambda: None, progress=lambda n: None):
    templates = [create_strategy(name) for name in names]
    versions = [s.version for s in templates]
    outcomes = [[] for _ in cards]
    for trial in range(trials):
        check()
        base = sampled_game(observation, Random(derived_seed(seed, f"branch-world:{trial}")))
        rng_states = [Random(derived_seed(seed, f"branch-policy:{trial}:{p}:{names[p]}:{versions[p]}")).getstate() for p in range(3)]
        for index, card in enumerate(cards):
            check()
            game = deepcopy(base)
            policies = [clone_strategy(s) for s in templates]
            rngs = [Random() for _ in range(3)]
            for rng, state in zip(rngs, rng_states):
                rng.setstate(state)
            first = True
            while not game.finished:
                check()
                observations = [game.observe(p) for p in range(3)]
                actions = []
                for p in range(3):
                    actions.append(card if first and p == observation.player else decide(policies[p], observations[p], rngs[p], False).card)
                    check()
                game.play(tuple(actions))
                first = False
            scores = game.observe(observation.player).game_scores
            score = scores[observation.player]
            best = 1 + sum(s > score for s in scores)
            worst = 3 - sum(s < score for s in scores)
            rank = str(best) if best == worst else f"{best}–{worst}"
            outcomes[index].append({"score": score, "win": int(observation.player in game.winners), "rank": rank})
        progress(trial + 1)
    paired = []
    for i in range(len(cards)):
        for j in range(i + 1, len(cards)):
            differences = [a["win"] - b["win"] for a, b in zip(outcomes[i], outcomes[j])]
            mean = sum(differences) / trials
            se = math.sqrt(sum((d - mean) ** 2 for d in differences) / (trials - 1) / trials) if trials > 1 else None
            paired.append({"a": asdict(cards[i]), "b": asdict(cards[j]), "win_rate_difference": mean,
                           "ci95": [max(-1, mean - 1.96 * se), min(1, mean + 1.96 * se)] if se is not None else None,
                           "average_score_difference": sum(a["score"] - b["score"] for a, b in zip(outcomes[i], outcomes[j])) / trials})
    return {"schema_version": 1, "position": position, "seed": seed, "trials": trials,
            "continuation": [{"name": name, "version": version} for name, version in zip(names, versions)],
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

