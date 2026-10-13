"""観測だけを使い、意思決定全体の仮想対局数を固定した探索。"""
from dataclasses import asdict, replace
from math import isfinite, log, sqrt
from random import Random
from time import perf_counter_ns

from .base import CandidateEvaluation, Decision, DecisionDetails
from .baselines import Baseline, NAMES
from .descriptions import AlgorithmDescription, ParameterDescription
from ..rollouts import rollout_trial

METHOD_NAMES = {"uniform": "budget_rollout", "heuristic": "hybrid_heuristic",
                "adaptive": "hybrid_adaptive", "combined": "hybrid_combined"}
MAX_TOTAL_BUDGET = 1024


class _Expired(Exception):
    pass


class HybridSearch:
    version = "1"

    def __init__(self, method="uniform", total_budget=64, continuation="Random", seed=None,
                 time_limit_ms=None, min_trials=1, priority_evaluator=None):
        if method not in METHOD_NAMES:
            raise ValueError("未知の総予算探索方式")
        if type(total_budget) is not int or not 1 <= total_budget <= MAX_TOTAL_BUDGET:
            raise ValueError(f"総予算は1〜{MAX_TOTAL_BUDGET}です")
        if type(min_trials) is not int or not 1 <= min_trials <= 8:
            raise ValueError("最低試行数は1〜8です")
        if continuation not in NAMES:
            raise ValueError("継続戦略は軽量5戦略に限定します")
        if seed is not None and type(seed) is not int:
            raise ValueError("seedは整数またはNoneです")
        if time_limit_ms is not None and (type(time_limit_ms) not in (int,float)
                or not isfinite(time_limit_ms) or not 0 <= time_limit_ms <= 5000):
            raise ValueError("時間上限は0〜5000msまたはNoneです")
        self.method, self.total_budget, self.continuation = method, total_budget, continuation
        self.seed, self.time_limit_ms, self.min_trials = seed, time_limit_ms, min_trials
        self.name = METHOD_NAMES[method]
        if priority_evaluator is not None and (method not in ('heuristic','combined') or not callable(getattr(priority_evaluator,'evaluate',None))):
            raise ValueError("優先評価器はHeuristic優先・組み合わせ方式にだけ注入できます")
        self.priority_evaluator=priority_evaluator

    @property
    def parameters(self):
        return {"method":self.method,"total_budget":self.total_budget,"continuation":self.continuation,
                "seed":self.seed,"time_limit_ms":self.time_limit_ms,"min_trials":self.min_trials,
                **({'priority_source':self.priority_evaluator.parameters} if self.priority_evaluator is not None else {})}

    def choose(self, observation, rng):
        return self._choose(observation,rng,False)

    def choose_detailed(self, observation, rng):
        return self._choose(observation,rng,True)

    def _choose(self, observation, rng, capture):
        started = perf_counter_ns()
        cards = tuple(sorted(observation.legal_actions))
        if not cards:
            raise ValueError("合法手がありません")
        observation = replace(observation,hand=tuple(sorted(observation.hand)))
        seed = self.seed if self.seed is not None else rng.getrandbits(128)
        outcomes = {c:[] for c in cards}
        counts = {"started":0,"finished":0}
        heuristic_ns = allocation_ns = 0
        heuristic = {}
        priority_details = None
        timed_out = False
        fallback = None
        priority = cards
        def check():
            if self.time_limit_ms is not None and (perf_counter_ns()-started)/1e6 >= self.time_limit_ms:
                raise _Expired
        def on_game(stage):
            counts[stage] += 1
        templates = [Baseline(self.continuation) for _ in range(3)]
        if len(cards)==1:
            fallback = "合法手が1枚のため探索不要"
        elif self.total_budget < len(cards)*self.min_trials:
            fallback = "全候補の最低試行数に予算が足りないため、探索せずカード順の合法手へ退避"
        else:
            try:
                check()
                if self.method in ("heuristic","combined"):
                    clock=perf_counter_ns()
                    try:
                        if self.priority_evaluator is None:
                            detail=Baseline("Heuristic").choose_detailed(observation,Random(0)).details
                            heuristic={c.card:c.score for c in detail.candidates}
                        else:
                            heuristic,priority_details=self.priority_evaluator.evaluate(observation)
                            if set(heuristic)!=set(cards) or any(not isfinite(v) for v in heuristic.values()):
                                raise ValueError("優先評価器は全合法手の有限値を返す必要があります")
                        priority=tuple(sorted(cards,key=lambda c:(-heuristic[c],c)))
                    finally:
                        heuristic_ns=perf_counter_ns()-clock
                    check()
                # 初期評価は全候補同じtrial番号。中断した一巡は採用しない。
                for trial in range(self.min_trials):
                    rows=rollout_trial(observation,cards,templates,seed,trial,check,on_game=on_game)
                    check()
                    for card,row in zip(cards,rows):
                        outcomes[card].append(row)
                while counts["started"] < self.total_budget:
                    check()
                    clock=perf_counter_ns()
                    if self.method=="uniform":
                        card=min(cards,key=lambda c:(len(outcomes[c]),c))
                    elif self.method=="heuristic":
                        top=priority[:max(1,(len(cards)+3)//4)]
                        card=min(top,key=lambda c:(len(outcomes[c]),priority.index(c)))
                    else:
                        total=sum(map(len,outcomes.values()))
                        def upper(c):
                            n=len(outcomes[c]);mean=sum(r['reward'] for r in outcomes[c])/n
                            optimism=4*sqrt(2*log(total+1)/n)
                            prior=(len(cards)-1-priority.index(c))/max(1,len(cards)-1) if self.method=="combined" else 0
                            return mean+optimism+prior/(n+1)
                        card=max(cards,key=lambda c:(upper(c),-priority.index(c)))
                    allocation_ns+=perf_counter_ns()-clock
                    trial=len(outcomes[card])
                    row=rollout_trial(observation,(card,),templates,seed,trial,check,on_game=on_game)[0]
                    check()
                    outcomes[card].append(row)
            except _Expired:
                timed_out=True
        fully_evaluated=all(len(rows)>=self.min_trials for rows in outcomes.values())
        means={c:sum(r['reward'] for r in rows)/len(rows) for c,rows in outcomes.items() if rows}
        if fully_evaluated:
            chosen=max(cards,key=lambda c:(means[c],-cards.index(c)))
            explanation=f"総予算{self.total_budget}内の{counts['finished']}仮想対局で、平均終局報酬が最大の{chosen.label}を選択（{means[chosen]:.3f}）"
        else:
            chosen=cards[0]
            fallback=fallback or "時間上限で全候補の初期評価が揃わず、カード順の合法手へ退避"
            explanation=fallback
        details=None
        if capture:
            stats=[]
            for card,rows in outcomes.items():
                n=len(rows)
                stats.append({"card":asdict(card),"trials":n,"average_terminal_reward":means.get(card),
                    "sole_win_rate":sum(r['sole_win'] for r in rows)/n if n else None,
                    "joint_win_rate":sum(r['joint_win'] for r in rows)/n if n else None,
                    "average_score":sum(r['score'] for r in rows)/n if n else None,
                    "reward_std":sqrt(sum((r['reward']-means[card])**2 for r in rows)/(n-1)) if n>1 else None,
                    "reward_ci95":None,"heuristic_score":heuristic.get(card)})
            accepted=sum(map(len,outcomes.values()))
            ranked=sorted(means,key=lambda c:(-means[c],c))
            details=DecisionDetails(
                candidates=tuple(CandidateEvaluation(c,means.get(c),
                    f"{len(outcomes[c])}試行。終局報酬平均で比較。適応配分の選択バイアスを含むため候補区間は未提供。" if outcomes[c] else "未評価。評価値は付けません。",
                    {"trials":len(outcomes[c]),**({("theory_priority_score" if self.priority_evaluator is not None else "heuristic_priority_score"):heuristic[c]} if c in heuristic else {})}) for c in cards),
                reasoning=(f"方式{self.method}。全候補を最低{self.min_trials}回評価し、残り予算を配分。",explanation,
                           ("Theory" if self.priority_evaluator is not None else "Heuristic")+"/UCB値は配分にだけ利用。最終選択には終局報酬平均だけを使います。"),
                score_label="期待終局報酬（仮想対局の標本平均、−2〜+2）",
                information_used=("本人の手札と合法手","公開履歴・得点・ターン・残り枚数"),
                estimates=("一様な未知札サンプリング。実際の相手手札は使いません。",
                           "適応割当・最良候補選択の偏りと少数試行のため、候補の95%区間は未提供です。",
                           "同じ候補内の試行番号を共有。同じ番号が実行された候補間だけ世界と初期乱数が共通です。"),
                optional_metadata={"kind":"hybrid_search","parameters":self.parameters,"seed":str(seed),
                    "total_budget":self.total_budget,"unused_budget":self.total_budget-counts['started'],
                    "started_games":counts['started'],"executed_games":counts['finished'],"completed_games":accepted,
                    "candidate_count":len(cards),"timed_out":timed_out,"fallback":fallback,"candidates":stats,
                    "heuristic_ms":heuristic_ns/1e6,"allocation_ms":allocation_ns/1e6,
                    "elapsed_ms":(perf_counter_ns()-started)/1e6,"sampler":"uniform-unseen-v1",
                    "best_runner_up_mean_gap":means[ranked[0]]-means[ranked[1]] if len(ranked)>1 else None,
                    "gap_note":"対応差の信頼区間ではありません。候補ごとの標本数が異なり得ます。",
                    **({'priority_evaluations':priority_details,'priority_source':self.priority_evaluator.parameters} if self.priority_evaluator is not None else {})})
        return Decision(chosen,explanation=explanation,details=details)


def description(method):
    approaches={"uniform":"全候補へ順番にほぼ均等に配分します。端数はカード順です。",
                "heuristic":"既存Heuristicで上位4分の1を選び、その候補へ追加試行を均等配分します。",
                "adaptive":"報酬平均と試行数に応じたUCB型の楽観値で追加先を選びます。候補を永久除外しません。",
                "combined":"Heuristicの順位に応じた小さな優先項をUCB型の配分値に加え、試行数とともに弱めます。"}
    return AlgorithmDescription(tagline=approaches[method],overview="意思決定全体の仮想対局数を制限して、平均終局報酬が最大の合法手を選びます。"+approaches[method],
        steps=("本人の観測から未知の手札候補を作る。","全候補に最低試行を配分。予算不足なら探索を行わず退避。",approaches[method],"最終選択は終局報酬平均のみ。同点はカード順。"),
        information=("自分の手札・公開履歴・得点・残り枚数",),
        strengths=("同じ総Rollout予算で、試行配分の効果を比較できます。",),
        weaknesses=("継続戦略と一様サンプリングに依存します。少数試行や適応選択には偏りがあります。",),
        randomness="対局rngから探索seedを取得。固定seedでも設定可能。時間上限なしで結果を再現。",
        implementation="総予算Monte Carlo Rollout（探索木は作りません）",
        parameters=(ParameterDescription("total_budget","意思決定全体の上限。1〜1024。","64"),
                    ParameterDescription("min_trials","全候補の最低試行数。1〜8。","1"),
                    ParameterDescription("continuation","軽量5戦略のみ。全席を登録初期状態から開始。","Random"),
                    ParameterDescription("seed","固定整数または対局rng。","None"),
                    ParameterDescription("time_limit_ms","協調時間上限0〜5000ms。途中試行も消費予算として記録。","None")),
        notes=("Heuristicの点数は終局報酬へ加算しません。","総Rollout数の公平性と時間の公平性は別です。候補評価の区間は未提供。"))
