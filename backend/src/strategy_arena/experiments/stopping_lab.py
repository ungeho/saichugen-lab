"""停止規則を固定した検証配札のPlan。既存保存・ワーカーを再利用。"""
from collections import Counter
from contextvars import ContextVar
from dataclasses import asdict
from typing import Literal
from pydantic import Field,model_validator
from .adaptive_lab import AdaptiveConfig,AdaptiveJobs,adaptive_estimate
from .stopping_analysis import rule_fingerprint,trace_sink,analyze_stopping,select_validation_positions,stopping_summary
from .evolution import digest

job_context=ContextVar('stopping_job_context',default=None)
CLASSES=('strict_middle','highest','lowest','tie')
PERIODS=('early','middle','before_final_round','final_round_start','final_round')

class StoppingConfig(AdaptiveConfig):
    name:str=Field(default='固定停止規則・独立検証パイロット',min_length=1,max_length=100)
    partition:Literal['validation']='validation'
    start_offset:int=Field(default=1900000,strict=True,ge=1000000,le=1999900)
    deals:int=Field(default=2,strict=True,ge=1,le=4)
    turns:list[int]=Field(default=[3,6,11,13],min_length=1,max_length=8)
    max_positions:int=Field(default=4,strict=True,ge=1,le=8)
    budgets:list[Literal[16,32,64,128,256]]=Field(default=[32],min_length=1,max_length=5)
    initial_worlds:Literal[16]=16
    batch_worlds:Literal[16]=16
    gap_threshold:Literal[.5]=.5
    uncertainty_z:Literal[2]=2
    minimum_gap:Literal[.05]=.05
    reference_worlds:int=Field(default=16,strict=True,ge=16,le=256)
    final_worlds:int=Field(default=16,strict=True,ge=16,le=256)
    historical_limit:Literal[0]=0
    diagnostic_source_id:None=None
    cross_models:Literal[False]=False
    hypothesis:str=Field(default='Phase 32の停止規則を固定し、事前選択した全検証局面の計算量と独立評価報酬を比較する。早期停止0も有効な結果。',min_length=1,max_length=2000)

    @model_validator(mode='after')
    def fixed_values(self):
        if self.collectors!=['Random','Heuristic','ScoreAware','Zigzag','Reverse Zigzag']:raise ValueError('検証の5収集元を固定')
        if self.start_offset+self.deals>2000000:raise ValueError('最終評価配札は使用しません')
        return self

class StoppingJobs(AdaptiveJobs):
    kind='adaptive_stopping_validation_v1'
    config_type=StoppingConfig
    estimate=staticmethod(adaptive_estimate)

    def plan_extras(self,c):
        conditions={k:c.model_dump(mode='json')[k] for k in ('initial_worlds','batch_worlds','gap_threshold','uncertainty_z','minimum_gap','budgets','budget_mode','games_per_policy')}
        plan={'version':'stopping-validation-plan-v1','rules_hash':rule_fingerprint(),'conditions':conditions,
              'position_selection':'進行時点を巡回し、実配札・得点層・収集元の使用数を均す。Hashで固定タイブレーク。',
              'strata':{'classes':CLASSES,'periods':PERIODS},'primary_comparisons':['Gap-Adaptive - Fixed','Uncertainty-Adaptive - Fixed'],
              'primary_outcomes':['independent_final_reward','derived_games'],'primary_population':'全ての事前選択局面。停止／計算削減だけで選抜しない。',
              'multiplicity_bound':10000,'alpha':.05,'stop_rate_interval':'独立配札平均の有界Hoeffding。局面単位の二項区間ではない。',
              'analysis_unit':'反復→局面→実配札の平均。モデル・予算・層を合算しない。',
              'inference':'既存の探索的停止規則を固定した検証。小標本では確証しない。同等性検証は未登録。'}
        return {'stopping_plan':plan,'stopping_plan_hash':digest(plan)}

    def begin_run(self,v):
        v['stopping_trace']=[];v['planned_positions']=[]
        return job_context.set(v),trace_sink.set(lambda entry:v['stopping_trace'].append(entry))

    def finish_run(self,v,token):
        for s in v['stopping_trace']:
            if not s['selection_completed']:
                s['classification']='cancelled' if v['status']=='Cancelled' else 'max_derived_games' if v['status']=='BudgetExceeded' else 'timed_out' if v['status']=='TimedOut' else 'invalid_or_insufficient_samples'
                s['job_terminal_status']=v['status']
                if s['checkpoints']:s['checkpoints'][-1]['final_stop_reason']=s['classification']
        trace_sink.reset(token[1]);job_context.reset(token[0])

    def result_content(self,v):return {**super().result_content(v),'stopping_trace':v.get('stopping_trace',[]),'planned_positions':v.get('planned_positions',[])}

    def collect_positions(self,c,check,progress,snapshot):
        records,observations,summary=super().collect_positions(c,check,progress,snapshot)
        chosen=select_validation_positions(records,c.max_positions);v=job_context.get()
        v['planned_positions']=[{k:r[k] for k in ('position_hash','deal_hash','observation_hash','period','stratum','source','turn')} for r in chosen]
        summary['planned_positions']=len(chosen);summary['planned_independent_deals']=len({r['deal_hash'] for r in chosen})
        return records,observations,summary

    def position_results(self,c,records,observations,check,progress):
        for r in select_validation_positions(records,c.max_positions):
            obs=observations[r['position_hash']]
            yield {**r,'position_id':r['position_hash'],'observation':asdict(obs),'labels':[r['stratum']['class']],
                   'search':{'reversals':[]},'validation':None,'adaptive':analyze_stopping(obs,c,r['position_hash'],check,progress)}

    summarize_positions=staticmethod(stopping_summary)

    def get(self,identifier):
        v=super().get(identifier)
        if v['status']=='Invalidated':v.update(stopping_trace=[],planned_positions=[])
        planned=v.get('planned_positions',[]);complete={p['position_hash'] for p in v['positions']}
        v['job_termination_reason']='cancelled' if v['status']=='Cancelled' else 'max_derived_games' if v['status']=='BudgetExceeded' else 'timed_out' if v['status']=='TimedOut' else 'invalid_or_insufficient_samples' if v['status'] in ('Failed','Interrupted','Invalidated') else v['status']
        v['missing_positions']=[r['position_hash'] for r in planned if r['position_hash'] not in complete]
        v['stop_reason_counts']=dict(Counter(s['classification'] for s in v.get('stopping_trace',[])))
        v['coverage']=[{'class':cls,'period':period,'collected':sum(r['stratum']['class']==cls and r['period']==period for r in v.get('inventory',[])),
                       'planned':sum(r['stratum']['class']==cls and r['period']==period for r in planned),
                       'evaluated':sum(r['stratum']['class']==cls and r['period']==period for r in v['positions']),
                       'status':'evaluated' if any(r['stratum']['class']==cls and r['period']==period for r in v['positions']) else 'not_evaluated'} for cls in CLASSES for period in PERIODS]
        if v['status']!='Completed':v['cluster_summary']=None
        return v
