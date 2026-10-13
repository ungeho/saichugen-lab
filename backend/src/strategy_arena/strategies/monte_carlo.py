"""不完全情報の仮想対局によって期待終局報酬を最大化する。"""
from dataclasses import asdict, replace
from math import isfinite, sqrt
from random import Random
from time import perf_counter_ns

from .base import CandidateEvaluation, Decision, DecisionDetails
from .baselines import Baseline, NAMES
from .descriptions import AlgorithmDescription, ParameterDescription
from ..rollouts import rollout_trial


MAX_TRIALS = 64


class _BudgetExpired(Exception):
    pass


class MonteCarloRollout:
    name = "monte_carlo_rollout"
    version = "1"

    def __init__(self, trials=8, continuation="Random", seed=None, time_limit_ms=None):
        if type(trials) is not int or not 1 <= trials <= MAX_TRIALS:
            raise ValueError(f"候補あたりの試行回数は1〜{MAX_TRIALS}です")
        if continuation not in NAMES:
            raise ValueError("Rolloutの継続戦略は既存の軽量5戦略に限定します")
        if seed is not None and type(seed) is not int:
            raise ValueError("seedは整数またはNoneです")
        if time_limit_ms is not None and (type(time_limit_ms) not in (int, float)
                or not isfinite(time_limit_ms) or not 0 <= time_limit_ms <= 5000):
            raise ValueError("時間上限は0〜5000msまたはNoneです")
        self.trials, self.continuation = trials, continuation
        self.seed, self.time_limit_ms = seed, time_limit_ms

    @property
    def parameters(self):
        return {"trials": self.trials, "continuation": self.continuation,
                "seed": self.seed, "time_limit_ms": self.time_limit_ms}

    def choose(self, observation, rng: Random):
        return self._choose(observation, rng, False)

    def choose_detailed(self, observation, rng: Random):
        return self._choose(observation, rng, True)

    def _choose(self, observation, rng, capture):
        started = perf_counter_ns()
        cards = tuple(sorted(observation.legal_actions))
        if not cards:
            raise ValueError("選択できるカードがありません")
        # 表示上の手札順で世界・継続Randomの選択が変わらないよう正規化する。
        observation = replace(observation, hand=tuple(sorted(observation.hand)))
        seed = self.seed if self.seed is not None else rng.getrandbits(128)
        outcomes = [[] for _ in cards]
        completed = 0
        fallback = "合法手が1枚のため探索不要" if len(cards) == 1 else None
        timed_out = False
        game_counts = {"started": 0, "finished": 0}

        def on_game(stage):
            game_counts[stage] += 1

        def check():
            if self.time_limit_ms is not None and (perf_counter_ns() - started) / 1e6 >= self.time_limit_ms:
                raise _BudgetExpired

        if len(cards) > 1:
            templates = [Baseline(self.continuation) for _ in range(3)]
            for trial in range(self.trials):
                try:
                    check()
                    rows = rollout_trial(observation, cards, templates, seed, trial, check, on_game=on_game)
                    check()
                except _BudgetExpired:
                    timed_out = True
                    break
                # 不完全な試行を混ぜず、全候補へ同じ試行数を適用する。
                for samples, row in zip(outcomes, rows):
                    samples.append(row)
                completed += 1
        totals = [sum(row["reward"] for row in rows) for rows in outcomes]
        if completed:
            best_index = max(range(len(cards)), key=lambda i: totals[i])
            explanation = f"共通の{completed}試行で期待終局報酬が最大の{cards[best_index].label}を選択（{totals[best_index]/completed:.3f}）"
        else:
            best_index = 0
            fallback = fallback or "時間上限までに共通試行が完了せず、カード順で先頭の合法手を選択"
            explanation = fallback
        details = None
        if capture:
            stats = []
            for card, rows, total in zip(cards, outcomes, totals):
                mean = total / completed if completed else None
                std = sqrt(sum((r["reward"] - mean) ** 2 for r in rows) / (completed - 1)) if completed > 1 else None
                ci = [max(-2, mean - 1.96 * std / sqrt(completed)), min(2, mean + 1.96 * std / sqrt(completed))] if std is not None else None
                stats.append({"card": asdict(card), "trials": completed, "average_terminal_reward": mean,
                              "sole_win_rate": sum(r["sole_win"] for r in rows)/completed if completed else None,
                              "joint_win_rate": sum(r["joint_win"] for r in rows)/completed if completed else None,
                              "average_score": sum(r["score"] for r in rows)/completed if completed else None,
                              "reward_std": std, "reward_ci95": ci})
            pair = None
            if completed and len(cards) > 1:
                from ..branch_simulation import paired_reward_statistics
                ranked = sorted(range(len(cards)), key=lambda i: (-totals[i], cards[i]))
                first, second = ranked[:2]
                pair = {"best": asdict(cards[first]), "runner_up": asdict(cards[second]),
                        **paired_reward_statistics([r["reward"] for r in outcomes[first]], [r["reward"] for r in outcomes[second]])}
            elapsed = (perf_counter_ns() - started) / 1e6
            details = DecisionDetails(
                candidates=tuple(CandidateEvaluation(
                    card, stat["average_terminal_reward"],
                    (f"{completed}試行の終局報酬平均。95%区間 {stat['reward_ci95']}。補助指標は選択点に加算しません。" if completed else "未評価。仮の評価値は付けません。"),
                    {"trials": completed, **{k: stat[k] for k in ("sole_win_rate", "joint_win_rate", "average_score", "reward_std") if stat[k] is not None}})
                    for card, stat in zip(cards, stats)),
                reasoning=("本人の手札・公開履歴だけから未知札を一様に配分しました。",
                           f"全候補で世界と席別初期乱数を共有し、継続戦略{self.continuation}で終局まで進めました。",
                           explanation, "同点は数字・スートの順で先頭。補助指標は選択に使いません。"),
                score_label="期待終局報酬（仮想対局の標本平均、−2〜+2）",
                information_used=("本人の手札と合法手", "公開済みカード・公開得点・ターン・残り枚数"),
                estimates=("一様サンプリング。相手の行動傾向や実際の隠し手札を参照しません。",
                           "95%区間は標本分散による正規近似。1試行では未提供。少数試行・分散0でも確実とは限りません。",
                           "継続戦略に依存する推定で、MCTSの木探索や最適プレイの証明ではありません。"),
                optional_metadata={"kind": "monte_carlo_rollout", "seed": str(seed), "parameters": self.parameters,
                                   "completed_trials": completed, "candidate_count": len(cards),
                                   "completed_games": completed * len(cards), "elapsed_ms": elapsed,
                                   "started_games": game_counts["started"], "executed_games": game_counts["finished"],
                                   "timed_out": timed_out, "fallback": fallback, "candidates": stats,
                                   "best_vs_runner_up": pair, "sampler": "uniform-unseen-v1",
                                   "continuation_version": "1", "state_policy": "registered_initial_v1"})
        return Decision(cards[best_index], explanation=explanation, details=details)


DESCRIPTION = AlgorithmDescription(
    tagline="仮想対局を繰り返し、最後の報酬が高い一手を選ぶ。",
    overview="出せるカードごとに残りのゲームを仮に遊び、勝者確定後の終局報酬の平均が最大のカードを選びます。今のターンの得点や勝率を直接最大化する戦略ではありません。",
    steps=("自分の手札と公開履歴から相手の手札候補を作る。", "同じ試行では全候補に同じ世界と初期乱数を使う。",
           "候補を最初の一手として固定し、全席を軽量戦略で終局まで進める。", "終局報酬の平均を比べ、最大のカードを選ぶ。同点はカード順。"),
    information=("自分の合法手・手札", "公開履歴・得点・ターン・残り枚数"),
    strengths=("今の獲得が最終的な単独・共同勝利にどうつながるかを見積もれます。",),
    weaknesses=("少数試行では選択が不安定です。継続戦略と一様な手札推定の偏りに影響されます。", "基本戦略より計算時間がかかります。"),
    randomness="外部の対局・比較シードから独立した探索seedを取得。固定seedも設定可能。同点はカード順。時間制限時は実行速度に依存します。",
    implementation="Monte Carlo Rollout（全候補を直接試す探索。MCTSの探索木・訪問回数による配分は使いません）",
    parameters=(ParameterDescription("trials", "候補ごとの試行数。増やすと時間も増加。1〜64。", "8"),
                ParameterDescription("continuation", "全席の継続戦略。既存5戦略のみ。推定結果に影響します。", "Random"),
                ParameterDescription("seed", "Noneなら対局側の乱数を利用。Pythonで固定整数も指定可能。", "None"),
                ParameterDescription("time_limit_ms", "任意の協調時間上限。途中試行は破棄、0完了なら合法手へ退避。0〜5000ms。", "None")),
    examples=("単独勝利は+2、2人共同勝利は+1、全員勝利は0。これらと敗北時の負報酬を平均して比較します。累計得点は加算しません。",),
    notes=("詳細設定はPythonのコンストラクタまたは設定付きfactory登録で指定します。画面は登録済み設定を使用します。",
           "全候補を同じ回数評価。標本の95%区間は仮定の誤りを含まず、強さを保証しません。"))
