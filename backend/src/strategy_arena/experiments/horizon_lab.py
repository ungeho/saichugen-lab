"""未使用検証配札・予算上限比較。既存workerとSQLite予約を再利用。"""
from collections import Counter
from dataclasses import asdict
from typing import Literal
from pydantic import Field,model_validator
from .stopping_lab import StoppingConfig,StoppingJobs,job_context
from .adaptive_lab import AdaptiveJobs
from .stopping_analysis import rule_fingerprint
from .horizon_analysis import analyze_horizon,horizon_summary
from .evolution import digest

def horizon_estimate(c):
    k=17-min(c.turns);selection=c.max_positions*k*max(c.budgets)*c.repeats*len(c.models)
    overhead=c.max_positions*k*(c.reference_worlds+c.final_worlds)*len(c.models);total=selection+overhead
    return {'independent_fresh_deals':c.deals,'positions_upper':c.max_positions,'legal_count_upper':k,
      'selection_games_upper':selection,'research_overhead_games_upper':overhead,'derived_games_upper':total,
      'simulated_turns_upper':total*(15-min(c.turns)),'collection_games':c.deals*len(c.collectors),
      'estimated_seconds_range':[total*.0005,total*.003+c.deals*len(c.collectors)*.1],
      'note':'最大経路を1回だけ計算し各上限を再構成。これは実研究計算の上限。反実仮想の全比較コストを加算しない。時間は未校正。'}

class HorizonConfig(StoppingConfig):
    name:str=Field(default='固定停止規則・予算上限パイロット',min_length=1,max_length=100)
    start_offset:int=Field(default=1910000,strict=True,ge=1000000,le=1999900)
    turns:list[int]=Field(default=[11,13],min_length=1,max_length=8)
    max_positions:int=Field(default=2,strict=True,ge=1,le=8)
    budgets:list[Literal[16,32,64,128,256]]=Field(default=[16,32,64,128,256],min_length=1,max_length=5)
    budget_mode:Literal['max_worlds']='max_worlds'
    hypothesis:str=Field(default='128世界のGap−Fixedの独立評価報酬差と派生対局差を主要比較とする。他予算・方式は副次。',min_length=1,max_length=2000)

    @model_validator(mode='after')
    def adaptive_valid(self):
        if self.initial_worlds>min(self.budgets):raise ValueError('初期世界数超過')
        if self.evaluation_worlds!=64 or self.safety_tolerance!=0:raise ValueError('旧互換設定は固定')
        if horizon_estimate(self)['derived_games_upper']>self.max_derived_games:raise ValueError('実研究派生対局の上限超過')
        if self.max_positions<self.deals:raise ValueError('独立配札ごとに最低1局面必要')
        if {1900000,1900001}&set(range(self.start_offset,self.start_offset+self.deals)):raise ValueError('Phase 33既観測配札は再利用しません')
        return self

def choose_positions(records,limit):
    selected=[];deals=Counter();periods=Counter();classes=Counter();sources=Counter()
    remaining=list(records)
    while remaining and len(selected)<limit:
        r=min(remaining,key=lambda r:(deals[r['deal_hash']],periods[r['period']],classes[r['stratum']['class']],sources[r['source']],r['position_hash']))
        remaining.remove(r);selected.append(r);deals[r['deal_hash']]+=1;periods[r['period']]+=1;classes[r['stratum']['class']]+=1;sources[r['source']]+=1
    return selected

class HorizonJobs(StoppingJobs):
    kind='stopping_horizon_v1'
    config_type=HorizonConfig
    estimate=staticmethod(horizon_estimate)

    def plan_extras(self,c):
        plan={'version':'stopping-horizon-v1','rules_hash':rule_fingerprint(),'horizons':c.budgets,
          'primary_priority':{'budget':128,'contrast':'Gap-Adaptive - Fixed','models':c.models,'outcomes':['independent_final_reward','derived_games']},
          'secondary':'他予算・方式・層。主要128が未設定なら主要比較は未評価。',
          'selection':'実配札の使用数を最優先、時点・得点層・収集元を均す。Hash昇順。結果を見る前に固定。',
          'multiplicity_bound':10000,'alpha':.05,'unit':'反復→局面→実配札。予算・モデルを合算しない。',
          'reconstruction':'最大Fixed経路のネストした16世界チェックポイント。停止後は研究用のみ。',
          'counterfactual_policy_cost':'世界・対局・手番のみ。elapsed_seconds=null。',
          'actual_research_compute_cost':'最大経路＋独立参照・最終評価の実測。収集は別。',
          'inference':'固定標本数。全局面で主分析。任意統計停止なし。小標本は確証しない。'}
        return {'horizon_plan':plan,'horizon_plan_hash':digest(plan)}

    def collect_positions(self,c,check,progress,snapshot):
        records,observations,summary=AdaptiveJobs.collect_positions(self,c,check,progress,snapshot)
        chosen=choose_positions(records,c.max_positions)
        job_context.get()['planned_positions']=[{k:r[k] for k in ('position_hash','deal_hash','observation_hash','period','stratum','source','turn')} for r in chosen]
        summary.update(planned_positions=len(chosen),planned_independent_deals=len({r['deal_hash'] for r in chosen}))
        return records,observations,summary

    def position_results(self,c,records,observations,check,progress):
        for r in choose_positions(records,c.max_positions):
            obs=observations[r['position_hash']]
            yield {**r,'position_id':r['position_hash'],'observation':asdict(obs),'labels':[r['stratum']['class']],
              'search':{'reversals':[]},'validation':None,'adaptive':analyze_horizon(obs,c,r['position_hash'],check,progress)}

    summarize_positions=staticmethod(horizon_summary)

    def get(self,identifier):
        v=super().get(identifier)
        v['cost_summary']['scope']='実研究コスト。完了局面の最大経路・参照・最終評価。部分局面はexecution_costを参照。反実仮想コストではない。'
        v['counterfactual_stop_reason_counts']=dict(Counter(r['classification'] for p in v['positions'] for r in p['adaptive']['rows']))
        return v
