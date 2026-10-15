"""粗粒度・入れ子区間の排他的計測と、説明可能な時間予測。乱数は使用しない。"""
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter,process_time
from typing import Literal
from pydantic import BaseModel,Field,ConfigDict,model_validator
from .evolution import digest
from .adaptive_analysis import execution_meter

active_ledger=ContextVar('cost_ledger',default=None)
position_context=ContextVar('cost_position',default={})

def counters():
    m=execution_meter.get()
    return (sum(m[s]['completed_games'] for s in ('policy','reference','final')),sum(m[s]['completed_simulated_turns'] for s in ('policy','reference','final'))) if m else (0,0)

@contextmanager
def stage_span(stage,**meta):
    ledger=active_ledger.get()
    if ledger is None:yield;return
    row={'id':len(ledger['rows']),'parent':ledger['stack'][-1]['id'] if ledger['stack'] else None,
      'stage':stage,'model':None,'period':None,'deal_id':None,'position_id':None,**position_context.get(),**meta,'wall_seconds':None,'cpu_seconds':None,'exclusive_wall_seconds':None,'exclusive_cpu_seconds':None,
      'derived_games':None,'simulated_turns':None,'items':1,'completed':False}
    ledger['rows'].append(row);ledger['stack'].append(row)
    g,t=counters();wall=perf_counter();cpu=process_time();row['interval_start']=wall
    try:yield row;row['completed']=True
    finally:
        row['interval_end']=perf_counter();row['wall_seconds']=row['interval_end']-wall;row['cpu_seconds']=process_time()-cpu
        children=[r for r in ledger['rows'] if r['parent']==row['id'] and r['wall_seconds'] is not None]
        row['exclusive_wall_seconds']=row['wall_seconds']-sum(r['wall_seconds'] for r in children)
        row['exclusive_cpu_seconds']=row['cpu_seconds']-sum(r['cpu_seconds'] for r in children)
        gg,tt=counters();row['inclusive_derived_games']=gg-g;row['inclusive_simulated_turns']=tt-t
        row['derived_games']=gg-g-sum(r['inclusive_derived_games'] for r in children);row['simulated_turns']=tt-t-sum(r['inclusive_simulated_turns'] for r in children)
        ledger['stack'].pop()

class TimedStore:
    def __init__(self,store):self.original=store
    def __getattr__(self,key):return getattr(self.original,key)
    def update(self,*args,**kwargs):
        with stage_span('sqlite_json_write') as row:
            if row is not None:kwargs['on_write']=row.update
            return self.original.update(*args,**kwargs)

def breakdown(rows,total):
    done=[r for r in rows if r.get('exclusive_wall_seconds') is not None]
    negative=[r['id'] for r in done if min(r['exclusive_wall_seconds'],r['exclusive_cpu_seconds'])<0]
    groups=defaultdict(lambda:{'wall_seconds':0.,'cpu_seconds':0.,'derived_games':0,'simulated_turns':0,'items':0})
    for r in done:
        out=groups[r['stage']]
        for key in out:out[key]+=r['exclusive_'+key] if key in ('wall_seconds','cpu_seconds') else r[key]
    measured=sum(r['exclusive_wall_seconds'] for r in done)
    duplicate=len({r['id'] for r in rows})!=len(rows)
    siblings=defaultdict(list)
    for r in done:siblings[r['parent']].append(r)
    overlap=any(a['interval_end']>b['interval_start']+1e-9 for xs in siblings.values() for a,b in zip(sorted(xs,key=lambda x:x['interval_start']),sorted(xs,key=lambda x:x['interval_start'])[1:]))
    return {'stages':dict(groups),'measured_exclusive_wall_seconds':measured,'total_wall_seconds':total,
      'unmeasured_residual_seconds':total-measured,'overlap_or_timer_error':bool(duplicate or overlap or negative or measured>total+.01),'negative_intervals':negative,
      'scope':'入れ子の子区間を親から控除した排他的集計。inclusiveの単純合計は禁止。最後の保存/応答処理等は未計測残差。負の残差を0へ補正しない。',
      'unmeasured_components':['収集内の配札生成/進行/抽出/合法性の個別内訳','世界生成/戦略判断/報酬の個別内訳','SQLiteとJSON直列化の個別内訳','最後の保存・応答等の管理内訳']}

class CalibrationModel(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version:Literal['stage-turn-rate-v1']='stage-turn-rate-v1'
    source_ids:list[str]=Field(min_length=1,max_length=30)
    source_deal_hashes:list[str]=Field(default=[],max_length=20000)
    environment:dict[str,str]=Field(default_factory=dict)
    rates:dict[str,float]
    slow_rates:dict[str,float]
    safety_factor:float=Field(default=1.5,ge=1.25,le=3)
    management_seconds:float=Field(default=10,ge=0,le=60)
    conservative_management_seconds:float=Field(default=30,ge=10,le=120)
    note:str=Field(min_length=1,max_length=2000)

    @model_validator(mode='after')
    def valid(self):
        import math
        keys={stage+':'+m for stage in ('policy','reference','final') for m in ('Random','Heuristic','ScoreAware')}
        if set(self.rates)!=keys or set(self.slow_rates)!=keys:raise ValueError('3段階×3モデルの校正値が必要')
        if any(not math.isfinite(v) or v<=0 or v>.1 for v in [*self.rates.values(),*self.slow_rates.values()]):raise ValueError('正の有限時間単価が必要')
        if any(self.slow_rates[k]<v for k,v in self.rates.items()):raise ValueError('保守単価は平均単価以上')
        if self.conservative_management_seconds<self.management_seconds:raise ValueError('保守管理費は通常管理費以上')
        return self

def fit_calibration(jobs):
    """同環境の完了した区間だけ。TimedOutの全体時間を完了対局の単価にしない。"""
    samples=defaultdict(list);ids=[];hashes=set();env=None
    for v in jobs:
        if v['config'].get('revision') not in ('phase38','phase39'):raise ValueError('計測方式の異なる旧系列は混合しません')
        if v['config'].get('revision')=='phase39' and v['config']['stage']=='independent_validation':raise ValueError('Phase 39の独立検証は校正へ戻しません')
        raw=v['snapshot']['study_plan']['environment'];e={k:raw[k] for k in ('os','cpu','python')}
        if env is not None and e!=env:raise ValueError('測定環境が異なります')
        env=e;ids.append(v['id']);hashes.update(v['snapshot']['deal_hashes'])
        if v.get('stage_measurements'):
            for r in v['stage_measurements']:
                stage='policy' if r['stage'] in ('policy_reconstruction','policy_direct') else r['stage']
                if stage in ('policy','reference','final') and r.get('completed') and r.get('simulated_turns',0)>0 and r['exclusive_wall_seconds']>0:samples[stage+':'+r['model']].append((r['exclusive_wall_seconds'],r['simulated_turns']))
        else:
            for p in v['positions']:
                a=p['adaptive']
                for path in a['research_paths']:
                    cost=path['cost'];samples['policy:'+path['model']].append((cost['elapsed_seconds'],cost['simulated_turns']))
                for stage in ('reference','final'):
                    for model,r in a[stage].items():samples[stage+':'+model].append((r['cost']['elapsed_seconds'],r['cost']['simulated_turns']))
            for r in v.get('runtime_measurements',[]):
                if r.get('measurement_completed') and r.get('cost',{}).get('simulated_turns',0)>0:samples['policy:'+r['model']].append((r['wall_seconds'],r['cost']['simulated_turns']))
    rates={k:sum(t for t,n in xs)/sum(n for t,n in xs) for k,xs in samples.items()}
    slow={k:max(t/n for t,n in xs) for k,xs in samples.items()}
    return CalibrationModel(source_ids=ids,source_deal_hashes=sorted(hashes),environment=env or {},rates=rates,slow_rates=slow,
      note='同環境・Phase38/39の完了区間の秒/シミュレーション手番。policyの平均単価と段階別最大単価×1.5、管理余裕10/30秒を配札ごとに加算。旧区間は保存処理を含む場合がある。時点別観測を単価に含むが層別係数は少数のため推定しない。未観測条件と打切りの選択バイアスを保証しない。')

def forecast(c,estimate):
    if c.calibration is None:return {'rating':'データ不足で判断困難','predicted_seconds':None,'conservative_seconds':None,'guarantee':False}
    model=c.calibration
    if model.version=='coverage-turn-rate-v2':
        from .calibration_coverage import forecast_coverage
        return forecast_coverage(c,estimate)
    from .stratification_analysis import period
    slots={p:max((17-t for t in c.turns if ('final_round' if period(t)=='final_round_start' else period(t))==p),default=0) for p in ('early','middle','before_final_round','final_round')}
    times={p:max((15-t for t in c.turns if ('final_round' if period(t)=='final_round_start' else period(t))==p),default=0) for p in slots}
    active=[p for p in slots if slots[p]]
    units=sum(slots[active[i%len(active)]]*times[active[i%len(active)]] for i in range(c.deals))
    turns={'policy':units*512,'reference':units*c.reference_worlds,'final':units*c.final_worlds}
    if c.warmups:turns['policy']+=(17-min(c.turns))*(15-min(c.turns))*48*c.warmups
    predicted=sum(turns[s]*model.rates[s+':'+m] for s in turns for m in c.models)+model.management_seconds*c.deals
    slow=sum(turns[s]*model.slow_rates[s+':'+m] for s in turns for m in c.models)*model.safety_factor+model.conservative_management_seconds*c.deals
    return {'model_hash':digest(model.model_dump(mode='json')),'source_ids':model.source_ids,'predicted_seconds':predicted,'conservative_seconds':slow,
      'derived_games_upper':estimate['derived_games_upper'],'simulated_turns_upper':sum(turns.values())*len(c.models),
      'timeout_seconds':c.timeout_seconds,'rating':'予算内の見込み' if slow<=c.timeout_seconds and estimate['derived_games_upper']<=c.max_derived_games else '予算超過のおそれ',
      'reliability':'低い。少数の完了区間・過去の打切りを含む校正。未観測の遅い条件を保証しない。',
      'scope':model.note,'guarantee':False}

def deal_progress(v):
    complete={p['position_hash'] for p in v.get('positions',[])}
    touched={r.get('position_hash') for r in v.get('runtime_measurements',[])}|{r.get('position_hash') for r in v.get('stopping_trace',[])}|{r.get('position_id') for r in v.get('stage_measurements',[])}
    out=[]
    for index,p in enumerate(v.get('planned_positions',[])):
        pid=p['position_hash'];rs=[r for r in v.get('runtime_measurements',[]) if r.get('position_hash')==pid]
        out.append({**p,'ordinal':index,'evaluation_state':'complete' if pid in complete else 'partial' if pid in touched else 'not_started',
          'completed_direct_intervals':sum(r.get('measurement_completed',False) for r in rs),'attempted_direct_intervals':len(rs),
          'measured_direct_seconds':sum(r.get('wall_seconds') or 0 for r in rs),'termination':v['status']})
    by=defaultdict(list)
    for r in out:by[r['deal_hash']].append(r['evaluation_state'])
    for dh in v.get('snapshot',{}).get('deal_hashes',[]):
        if dh not in by:by[dh]=['not_started']
    deals=[{'deal_hash':dh,'evaluation_state':'complete' if all(s=='complete' for s in ss) else 'partial' if any(s in ('complete','partial') for s in ss) else 'not_started'} for dh,ss in by.items()]
    return {'positions':out,'deals':deals,'counts':{s:sum(r['evaluation_state']==s for r in deals) for s in ('complete','partial','not_started')},
      'bias_warning':'実行順序と計算コストに関係があると完了部分は偏る可能性がある。部分結果を主要集約にしない。',
      'scope':'収集済みではなく評価段階の状態。未計測時間を0とは扱わない。direct秒は完了した直接計時区間だけ。'}

def completion_audit(v):
    c=v['config'];positions=v.get('positions',[]);expected={(m,method,0,128) for m in c['models'] for method in ('Fixed','Gap-Adaptive','Uncertainty-Adaptive')}
    rows_ok=all(len(p['adaptive']['rows'])==len(expected) and {(r['model'],r['method'],r['repeat'],r['budget']) for r in p['adaptive']['rows']}==expected and all(r.get('direct_measurement',{}).get('measurement_completed') and len(r.get('evaluations',[]))==1 and r['evaluations'][0]['model']==r['model'] and all(k in r['evaluations'][0] for k in ('minus_fixed','minus_self','estimated_regret')) for r in p['adaptive']['rows']) for p in positions)
    samples_ok=all(all(len(p['adaptive'].get(role,{}).get(m,{}).get('candidates',[]))==p['adaptive']['legal_count'] and p['adaptive'][role][m]['cost']['derived_games']==p['adaptive']['legal_count']*c[role+'_worlds'] for m in c['models']) for p in positions for role in ('reference','final'))
    checks={'completed_status':v['status']=='Completed','all_deals':len({p['deal_hash'] for p in positions})==c['deals'],'all_positions':len(positions)==c['max_positions'],
      'all_models_methods_repeats_and_direct':rows_ok,'reference_final':samples_ok,'plan_hash':digest(v['snapshot']['study_plan'])==v['snapshot']['study_plan_hash'],
      'within_time':v['elapsed_seconds']<=c['timeout_seconds'],'within_games':sum(v.get('execution_cost',{}).get(s,{}).get('started_games',0) for s in ('policy','reference','final'))<=c['max_derived_games'],
      'saved_result':bool(v.get('stored_result_hash') or v.get('result_hash'))}
    return {'checks':checks,'primary_finalized':all(checks.values())}
