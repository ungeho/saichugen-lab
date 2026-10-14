"""Phase 28の収集・登録・停止・保存を利用する意思決定比較。"""
from dataclasses import asdict
from typing import Literal
from pydantic import Field,model_validator
from .stratification_lab import StratificationConfig,StratificationJobs,stratification_estimate
from .decision_analysis import evaluate_rules,decision_positions,decision_summary


class DecisionConfig(StratificationConfig):
    name:str=Field(default='中間順位・4意思決定規則パイロット',min_length=1,max_length=100)
    start_offset:int=Field(default=11000,strict=True,ge=0,le=999900)
    validation_offset:int=Field(default=11000,strict=True,ge=0,le=999900)
    controls:int=Field(default=3,strict=True,ge=0,le=6)
    max_validate:Literal[0]=0
    evaluation_trials:int=Field(default=32,strict=True,ge=10,le=128)
    safety_tolerance:float=Field(default=0,ge=0,le=.1,allow_inf_nan=False)
    hypothesis:str=Field(default='厳密中間で直近2位率より得点差や安全余裕を考慮した札が有利になる局面を、選択と独立評価を分けて調べる。未検証。',min_length=1,max_length=2000)

    @model_validator(mode='after')
    def valid(self):
        super().valid()
        if decision_estimate(self)['derived_games_upper']>10000:raise ValueError('派生対局上限10000以内にしてください')
        return self


def decision_estimate(c):
    base=stratification_estimate(c);upper=c.max_positions*(17*c.trials+4*c.evaluation_trials)
    return {**base,'derived_games_upper':upper,'selection_games_upper':c.max_positions*17*c.trials,
        'evaluation_games_upper':c.max_positions*4*c.evaluation_trials,'estimated_seconds_range':[upper*.001+c.deals*.05,upper*.02+c.deals*len(c.collectors)*.1],
        'note':'4規則は同じ全合法手推定を共有。独立評価では同じ札を重複計算しない。時間は未校正。'}


class DecisionJobs(StratificationJobs):
    kind='middle_decision_v1'
    config_type=DecisionConfig
    estimate=staticmethod(decision_estimate)

    def registration_extras(self,c):
        return {**super().registration_extras(c),'decision_rules_version':'four-objectives-v1',
            'analysis_selection':'均衡・上側接近・下側接近・両側小差・両側大差を巡回、局面重複除外。配札・収集元を均し時点12,11,13,14,9,6,3優先。対照は最高・最低・同点。結果を見ない。',
            'validation_selection':'選抜した全局面で、選択した札を固定し独立世界で評価。不一致局面だけを評価しない。',
            'objectives':{'Self-Middle':'直近自己2位確率最大','Gap-Control':'次ラウンド境界の相手間累積得点差の平均最大',
                'Safety-Margin':'次境界の厳密中間確率最大から許容幅以内を残し、その中の中間条件付きminimum_margin最大',
                'Terminal-Value':'最終期待終局報酬最大'},
            'non_middle_margin':'中間条件付き平均はnull、非中間を正の安全余裕として使わない。全結果の符号付き最小差を別保存。',
            'tie_break':'ランク昇順、同ランクはスート昇順。Safetyは許容幅後のmarginも同点なら同じ順。',
            'comparison_family':'選択はmax_positions*(17+272*7)、独立評価はmax_positions*(4+12*7)。配札集約は4対比×最大20層。',
            'evaluation_partition':'validation-world-samples','sampling_bias':'結果を見る前の層別・時点優先選抜。母集団の確率標本ではない。'}

    def position_results(self,c,records,observations,check,progress):
        for record in decision_positions(records,c.max_positions,c.controls):
            check();pid=record['position_hash'];obs=observations[pid]
            search,decision=evaluate_rules(obs,c,pid,check,progress)
            yield {**record,'position_id':pid,'observation':asdict(obs),'labels':['中間得点' if record['stratum']['strict_middle'] else record['stratum']['class']],
                'rounds_remaining':5-obs.turn//3,'search':search,'decision':decision,'validation':None}

    def summarize_positions(self,positions):return decision_summary(positions)

    def get(self,identifier):
        v=super().get(identifier)
        if v['status']!='Invalidated':v['recommendations']=[{'action':'別配札・別継続での追試','reason':'選択と独立世界評価を分離した探索結果。Terminal-Valueも推定誤差を持ち、実戦戦略の優位性や因果機序は未確認。'}]
        return v
