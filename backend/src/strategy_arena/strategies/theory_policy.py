"""同じ仮説設定を直接選択と探索優先度に利用する。"""
from dataclasses import asdict

from .base import CandidateEvaluation, Decision, DecisionDetails
from .descriptions import AlgorithmDescription, ParameterDescription
from .theories import TheoryConfig, evaluate_combination, default_theories, theory_catalog
from .hybrid import HybridSearch


class TheoryPolicy:
    name='theory_policy'
    version='1'

    def __init__(self, config=None):
        self.config=TheoryConfig.model_validate(config) if config is not None else default_theories()

    @property
    def parameters(self):
        return {'theory_config':self.config.model_dump(),'parent_strategy':None}

    def evaluate(self,observation):
        rows=evaluate_combination(observation,self.config)
        return {r['card']:r['score'] for r in rows},[{**r,'card':asdict(r['card'])} for r in rows]

    def choose(self,observation,rng):
        return self._choose(observation,rng,False)

    def choose_detailed(self,observation,rng):
        return self._choose(observation,rng,True)

    def _choose(self,observation,rng,capture):
        rows=evaluate_combination(observation,self.config)
        if not rows:raise ValueError("合法手がありません")
        best=max(r['score'] for r in rows)
        tied=[r for r in rows if abs(r['score']-best)<1e-12]
        selected=rng.choice(tied) if self.config.tie_break=='seeded_random' else tied[0]
        tie_note='同点は対局seedで再現する乱択' if self.config.tie_break=='seeded_random' else '同点はカード順'
        explanation=f"未検証のTheory代理評価が最大の{selected['card'].label}を選択。{tie_note}。期待終局報酬ではありません。"
        details=None
        if capture:
            details=DecisionDetails(candidates=tuple(CandidateEvaluation(r['card'],r['score'],
                ' / '.join(t['id']+': '+t['explanation'] for t in r['terms']) or '有効な仮説なし。全候補0の対照条件。',
                {t['id']:t['contribution'] for t in r['terms']}) for r in rows),
                reasoning=('各仮説を−1〜+1の代理尺度で評価。','重みの絶対値合計で割り、寄与を合算。重みは未調整の実験設定。',explanation),
                score_label='Theoryの重み付き代理評価（−1〜+1、終局報酬ではない）',
                information_used=tuple(dict.fromkeys(info for d in theory_catalog() for info in d['information'] if any(s.id==d['id'] and s.enabled and s.weight!=0 for s in self.config.theories))),
                estimates=('すべて未検証の仮説です。確立された定石ではありません。','相手点固定・一様出札等の仮定は候補の内訳を参照。','仮説間で得点・公開分布を重複評価する可能性があります。'),
                optional_metadata={'kind':'theory_policy',**self.parameters,'evaluations':[{**r,'card':asdict(r['card'])} for r in rows]})
        return Decision(selected['card'],explanation=explanation,details=details)


class TheorySearch(HybridSearch):
    def __init__(self,config=None,adaptive=False,total_budget=64,continuation='Random',seed=None,time_limit_ms=None,min_trials=1):
        evaluator=TheoryPolicy(config)
        super().__init__('combined' if adaptive else 'heuristic',total_budget,continuation,seed,time_limit_ms,min_trials,evaluator)
        self.name='theory_search_adaptive' if adaptive else 'theory_search'


def description(search=False):
    return AlgorithmDescription(tagline='未検証の戦術仮説を独立して組み合わせる。',
        overview='仮説の評価と重みを記録して比較します。'+('Theory点は探索配分だけに使い、最終選択は期待終局報酬です。' if search else '最終選択は仮説の代理評価で、期待終局報酬ではありません。'),
        steps=('仮説の有効・無効と設定を確認。','本人の観測だけから各候補への寄与を評価。','寄与を合算し、直接選択または探索優先順位へ利用。'),
        information=('有効な仮説が使う手札・公開履歴・得点・ターン。詳細はTheory Lab。',),
        strengths=('単独効果・組み合わせを同じ設定形式で検証できます。',),
        weaknesses=('代理モデルは将来勝率ではなく、重み・仮定とも未検証です。',),
        randomness='評価関数は決定的。直接選択の同点は既定でseed付き乱択（カード順も設定可能）。探索版は対局rngと一様サンプリングを使用し、最終同点はカード順。',
        implementation='未検証のルールベース仮説'+('＋総予算Rollout' if search else ''),
        parameters=(ParameterDescription('theory_config','仮説ID・版・有効性・重み・個別パラメータ。Theory Labで編集。','強い札の温存＋ラウンド重視'),),
        notes=('仮説の有効性を示す主張ではありません。','通常画面は登録既定値、Theory Labは実験設定を使用。'))
