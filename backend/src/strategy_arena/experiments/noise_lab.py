"""時間ノイズRと独立判断分岐Dの事前登録。旧実験の意味は変更しない。"""
from dataclasses import asdict
from typing import Literal
from pydantic import Field,model_validator
from .runtime_lab import RuntimeConfig,RuntimeJobs
from .runtime_analysis import environment
from .horizon_lab import horizon_estimate
from .stopping_analysis import select_validation_positions,rule_fingerprint
from .stratification_analysis import period
from .noise_analysis import analyze_noise,analyze_divergence,study_summary
from .evolution import digest

def study_estimate(c):
    by={p:max((17-t for t in c.turns if ('final_round' if period(t)=='final_round_start' else period(t))==p),default=0) for p in ('early','middle','before_final_round','final_round')}
    active=[p for p in by if by[p]];ksum=sum(by[active[i%len(active)]] for i in range(c.max_positions))
    reconstruction=ksum*max(c.budgets)*len(c.models)*(1 if c.series=='R' else c.repeats)
    modes=2 if c.measure_stopping else 1
    warm=ksum*sum(c.budgets)*3*c.warmups*modes*len(c.models) if c.series=='R' else 0
    measured=ksum*sum(c.budgets)*3*c.measurement_repeats*modes*len(c.models) if c.series=='R' else 0
    extra=ksum*(c.reference_worlds+c.final_worlds)*len(c.models) if c.series=='D' else 0
    total=reconstruction+warm+measured+extra
    return {'series':c.series,'independent_fresh_deals':c.deals,'positions_upper':c.max_positions,'legal_count_upper':17-min(c.turns),
      'reconstruction_games_upper':reconstruction,'warmup_games_upper':warm,'measurement_games_upper':measured,
      'selection_games_upper':reconstruction+warm+measured,'research_overhead_games_upper':extra,'derived_games_upper':total,
      'simulated_turns_upper':total*(15-min(c.turns)),'collection_games':c.deals*len(c.collectors),
      'estimated_seconds_range':[total*.0005,total*(.006 if c.series=='R' and c.measure_stopping else .003)+c.deals*len(c.collectors)*.1],
      'note':'Rは同一入力の反復とwarmupを実計上、計測モードの摂動は通常群と別集約。Dは最大経路を1回計算し三標本を共有。時間は未校正。'}

class StudyConfig(RuntimeConfig):
    name:str=Field(default='Series R・実行時間ノイズパイロット',min_length=1,max_length=100)
    series:Literal['R','D']='R'
    start_offset:int=Field(default=36000,strict=True,ge=0,le=1999900)
    max_positions:int=Field(default=1,strict=True,ge=1,le=8)
    turns:list[int]=Field(default=[13],min_length=1,max_length=8)
    measurement_repeats:int=Field(default=3,strict=True,ge=2,le=10)
    warmups:int=Field(default=1,strict=True,ge=0,le=2)
    measure_stopping:bool=Field(default=False,strict=True)
    order_seed:int=Field(default=36001,strict=True,ge=0,le=999999)
    hypothesis:str=Field(default='Rは同一入力の実時間変動を記述。Dは128世界での全事前局面の判断分岐率と独立報酬差を評価。',min_length=1,max_length=2000)

    @model_validator(mode='after')
    def adaptive_valid(self):
        if self.evaluation_worlds!=64 or self.safety_tolerance!=0:raise ValueError('旧互換設定は固定')
        if self.max_positions<self.deals:raise ValueError('独立配札を優先し1配札1枠以上必要')
        if self.stage=='development_pilot' and (self.partition!='development' or self.start_offset+self.deals>1000000):raise ValueError('開発は開発配札だけ')
        if self.stage=='independent_validation' and (self.partition!='validation' or self.start_offset<1000000 or self.start_offset+self.deals>2000000):raise ValueError('検証は未使用検証配札だけ')
        if self.series=='R' and (self.stage!='development_pilot' or self.repeats!=2):raise ValueError('Rは開発測定系列。互換repeats=2、実反復はmeasurement_repeatsを使用')
        if self.series=='D' and self.stage=='independent_validation' and 128 not in self.budgets:raise ValueError('D検証は主要128世界を必須とします')
        if self.series=='D' and (self.warmups!=0 or self.measure_stopping):raise ValueError('Dは時間測定をしない。warmups=0、measure_stopping=falseを指定')
        if {1900000,1900001,1910000,1910001,1920000,1920001}&set(range(self.start_offset,self.start_offset+self.deals)):raise ValueError('既観測検証配札を再利用しません')
        if study_estimate(self)['derived_games_upper']>self.max_derived_games:raise ValueError('研究派生対局の事前上限超過')
        return self

class StudyJobs(RuntimeJobs):
    kind='runtime_divergence_v1'
    config_type=StudyConfig
    estimate=staticmethod(study_estimate)

    def plan_extras(self,c):
        env=environment(c);env.update(warmup=c.warmups>0,warmup_repeats=c.warmups if c.series=='R' else 0,
          measurement_repeats=c.measurement_repeats if c.series=='R' else None,
          prior_computation='Rは最大Fixed照合経路の後、設定したwarmupを実行してから測定。Dは最大経路・独立参照・最終評価だけで直接時間測定なし。',
          scope='Rの直接計時はselect呼出と任意profile設定/解除を含み、保存・収集・照合経路は除外。Dは判断分岐と独立評価のみ。',
          stop_check_scope='任意profile群だけ既存stopping関数のcall/return間を計時。profileの全イベント通知に伴う摂動を含む。通常群の判定時間はnull。')
        plan={'version':'runtime-divergence-v1','series':c.series,'stage':c.stage,'rules_version':'phase32-frozen-v1','rules_hash':rule_fingerprint(),
          'primary_comparisons':['Gap-Adaptive - Fixed','Uncertainty-Adaptive - Fixed'],'primary_budget':128 if c.series=='D' else c.budgets,
          'outcomes':['decision_divergence_rate','independent_reward_difference'] if c.series=='D' else ['runtime_distribution','instrumented_stopping_cost'],
          'sampling':'Dはselection/reference/finalの三標本。Rは同一policy seedを全測定反復で固定。',
          'unit':'Dは反復→局面→独立配札。Rは同一入力の時間分布であり測定反復は独立配札ではない。',
          'position_selection':'Phase 33の固定時点巡回、配札・得点層・収集元を均しHash順。結果を見て追加しない。',
          'denominator':'事前選択した全評価対象局面。分岐例だけを主分析しない。',
          'order':'noise-order-v1、方式×計測モードを専用seedでshuffle。warmupと測定を別に保存。','environment':env,
          'multiplicity_bound':10000,'alpha':.05,'inference':'小標本の記述。任意の統計停止なし。時間CIなし。分岐0は損失リスク0ではない。'}
        return {'study_plan':plan,'study_plan_hash':digest(plan)}

    def position_results(self,c,records,observations,check,progress):
        for r in select_validation_positions(records,c.max_positions):
            obs=observations[r['position_hash']];fn=analyze_noise if c.series=='R' else analyze_divergence
            yield {**r,'position_id':r['position_hash'],'observation':asdict(obs),'labels':[r['stratum']['class']],
              'search':{'reversals':[]},'validation':None,'adaptive':fn(obs,c,r['position_hash'],check,progress)}

    summarize_positions=staticmethod(study_summary)

    def get(self,identifier):
        v=super().get(identifier);v['measurement_environment']=v['snapshot'].get('study_plan',{}).get('environment')
        v['cost_summary']['scope']='研究実計算。Rは照合経路＋warmup＋測定、Dは最大経路＋参照＋最終評価。系列・計測モードを混ぜない。'
        v['series']=v['config']['series']
        v['evaluated_independent_deals']=len({p['deal_hash'] for p in v['positions']})
        v['evaluated_positions']=len(v['positions'])
        return v
