"""開発と独立検証を分けた直接実行時間の事前登録。"""
from collections import Counter
from dataclasses import asdict
from contextvars import ContextVar
from typing import Literal
from pydantic import Field,model_validator
from .horizon_lab import HorizonConfig,HorizonJobs
from .adaptive_lab import AdaptiveJobs
from .stopping_lab import job_context
from .stopping_analysis import select_validation_positions,rule_fingerprint,trace_sink
from .stratification_analysis import period
from .runtime_analysis import analyze_runtime,runtime_summary,runtime_sink,environment
from .evolution import digest

PERIOD_ORDER=('early','middle','before_final_round','final_round')
def normalized(p):return 'final_round' if p=='final_round_start' else p

def runtime_estimate(c):
    by={p:max((17-t for t in c.turns if normalized(period(t))==p),default=0) for p in PERIOD_ORDER}
    available=[p for p in PERIOD_ORDER if by[p]]
    ksum=sum(by[available[i%len(available)]] for i in range(c.max_positions)) if available else 0
    reconstruction=ksum*max(c.budgets)*c.repeats*len(c.models)
    direct=ksum*sum(c.budgets)*3*c.repeats*len(c.models)
    overhead=ksum*(c.reference_worlds+c.final_worlds)*len(c.models);total=reconstruction+direct+overhead
    return {'independent_fresh_deals':c.deals,'positions_upper':c.max_positions,'legal_count_upper':17-min(c.turns),
      'selection_games_upper':reconstruction+direct,'reconstruction_games_upper':reconstruction,'direct_games_upper':direct,
      'research_overhead_games_upper':overhead,'derived_games_upper':total,'simulated_turns_upper':total*(15-min(c.turns)),
      'collection_games':c.deals*len(c.collectors),'estimated_seconds_range':[total*.0005,total*.003+c.deals*len(c.collectors)*.1],
      'note':'時点巡回の事前枠ごとの候補数上限。最大経路＋全方式の直接実行＋参照・最終評価。時間は未校正。'}

class RuntimeConfig(HorizonConfig):
    name:str=Field(default='直接実行時間・開発パイロット',min_length=1,max_length=100)
    stage:Literal['development_pilot','independent_validation']='development_pilot'
    partition:Literal['development','validation']='development'
    start_offset:int=Field(default=33000,strict=True,ge=0,le=1999900)
    deals:int=Field(default=1,strict=True,ge=1,le=4)
    max_positions:int=Field(default=4,strict=True,ge=1,le=8)
    turns:list[int]=Field(default=[3,10,11,13],min_length=1,max_length=8)
    budgets:list[Literal[32,64,128,256]]=Field(default=[32],min_length=1,max_length=4)
    models:list[Literal['Random','Heuristic','ScoreAware']]=Field(default=['Random'],min_length=1,max_length=3)
    order_seed:int=Field(default=35001,strict=True,ge=0,le=999999)
    hypothesis:str=Field(default='128世界でのGap/Uncertainty−Fixedの直接実時間差と独立報酬差をモデル別に評価。他予算と層は副次。',min_length=1,max_length=2000)

    @model_validator(mode='after')
    def adaptive_valid(self):
        if self.evaluation_worlds!=64 or self.safety_tolerance!=0:raise ValueError('旧互換設定は固定')
        if self.max_positions<self.deals:raise ValueError('独立配札を優先し1配札1枠以上必要')
        if self.stage=='development_pilot' and (self.partition!='development' or self.start_offset+self.deals>1000000):raise ValueError('開発Pilotには開発配札だけ')
        if self.stage=='independent_validation' and (self.partition!='validation' or self.start_offset<1000000 or self.start_offset+self.deals>2000000):raise ValueError('独立検証には検証配札だけ')
        if self.stage=='independent_validation' and 128 not in self.budgets:raise ValueError('独立検証の主要予算128を含めてください')
        if {1900000,1900001,1910000,1910001}&set(range(self.start_offset,self.start_offset+self.deals)):raise ValueError('Phase 33/34既観測配札を再利用しない')
        if runtime_estimate(self)['derived_games_upper']>self.max_derived_games:raise ValueError('直接実行を含む事前派生対局上限超過')
        return self

class RuntimeJobs(HorizonJobs):
    kind='stopping_runtime_v1'
    config_type=RuntimeConfig
    estimate=staticmethod(runtime_estimate)

    def plan_extras(self,c):
        plan={'version':'stopping-runtime-v1','rules_version':'phase32-frozen-v1','rules_hash':rule_fingerprint(),
          'stage':c.stage,'horizons':c.budgets,'primary_budget':128,'primary_comparisons':['Gap-Adaptive - Fixed','Uncertainty-Adaptive - Fixed'],
          'primary_outcomes':['direct_wall_difference','independent_final_reward_difference'],
          'position_selection':'進行時点を固定順序で巡回、各時点内で実配札使用数を最優先・得点層・収集元・Hash順。',
          'order':'runtime-order-v1の専用seedで各局面/モデル/反復/予算の方式順序を入替。観測結果に依存しない。',
          'order_seed':str(c.order_seed),'measurement':environment(c),'analysis_unit':'反復→局面→独立実配札。予算・モデル・stageを合算しない。',
          'multiplicity_bound':10000,'alpha':.05,'timing_intervals':'記述のみ。時間CI未提供。報酬CIは既存の最低独立配札数を満たす場合だけ。',
          'warmup':False,'pilot_scope':'開発用動作・費用確認。確証評価ではない。',
          'missing':'中断・上限・失敗を完了と区別し、未完了局面の報酬比較を補わない。'}
        return {'runtime_plan':plan,'runtime_plan_hash':digest(plan)}

    def begin_run(self,v):
        parent=super().begin_run(v);v['runtime_measurements']=[]
        def accept(entry):
            entry['seed']=str(entry['seed']);v['stopping_trace'].append(entry)
        trace_token=trace_sink.set(accept)
        def measure(row):
            v['runtime_measurements'].append(row)
            self.store.update(self.active,v) # 計時開始前に現在の測定条件を保存。
        return parent,runtime_sink.set(measure),trace_token

    def finish_run(self,v,token):
        for r in v['runtime_measurements']:
            if not r['measurement_completed']:r['classification']=v['status'];r['job_terminal_status']=v['status']
        # research traceには64bit導出seedがあるため新Labでは十進文字列で保持。
        for r in v['stopping_trace']:r['seed']=str(r['seed'])
        runtime_sink.reset(token[1]);trace_sink.reset(token[2]);super().finish_run(v,token[0])

    def result_content(self,v):return {**super().result_content(v),'runtime_measurements':v.get('runtime_measurements',[])}

    def collect_positions(self,c,check,progress,snapshot):
        records,observations,summary=AdaptiveJobs.collect_positions(self,c,check,progress,snapshot)
        chosen=select_validation_positions(records,c.max_positions)
        job_context.get()['planned_positions']=[{k:r[k] for k in ('position_hash','deal_hash','observation_hash','period','stratum','source','turn')} for r in chosen]
        summary.update(planned_positions=len(chosen),planned_independent_deals=len({r['deal_hash'] for r in chosen}))
        return records,observations,summary

    def position_results(self,c,records,observations,check,progress):
        for r in select_validation_positions(records,c.max_positions):
            obs=observations[r['position_hash']]
            yield {**r,'position_id':r['position_hash'],'observation':asdict(obs),'labels':[r['stratum']['class']],
              'search':{'reversals':[]},'validation':None,'adaptive':analyze_runtime(obs,c,r['position_hash'],check,progress)}

    summarize_positions=staticmethod(runtime_summary)

    def get(self,identifier):
        v=super().get(identifier)
        if v['status']=='Invalidated':v['runtime_measurements']=[]
        # Running応答・DBの保存途中でもseedはNumberへ渡さない。
        for r in v.get('stopping_trace',[]):r['seed']=str(r['seed'])
        v['cost_summary']['scope']='実研究コスト=再構成最大経路＋全方式直接実行＋参照・最終評価。直接時間は各measurementを参照。'
        v['measurement_environment']=v['snapshot'].get('runtime_plan',{}).get('measurement')
        v['runtime_coverage']=[{'axis':axis,'value':label,'independent_deals':len({p['deal_hash'] for p in v['positions'] if getter(p)==label}),
          'evaluated':sum(getter(p)==label for p in v['positions']),
          'status':'evaluated' if any(getter(p)==label for p in v['positions']) else 'not_evaluated'}
          for axis,labels,getter in [('period',('early','middle','before_final_round','final_round_start','final_round'),lambda p:p['period']),
             ('class',('strict_middle','highest','lowest','tie'),lambda p:p['stratum']['class']),
             ('source',('Random','Heuristic','ScoreAware','Zigzag','Reverse Zigzag'),lambda p:p['source'])] for label in labels]
        return v
