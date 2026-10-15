"""計測方式を分離した校正棚卸しと、適用範囲を持つ事前予測。"""
from collections import defaultdict,Counter
from math import ceil,isfinite
from typing import Literal
import numpy as np
from pydantic import BaseModel,Field,ConfigDict,model_validator
from .budget_calibration import CalibrationModel
from .noise_analysis import stats
from .evolution import digest
from .stratification_analysis import period

PERIODS=('early','middle','before_final_round','final_round')
QUALITY=('使用可能','条件付き使用可能','使用不可','情報不足')
def normalized(p):return 'final_round' if p=='final_round_start' else p

def inventory(jobs):
    records=[]
    for v in jobs:
        snap=v.get('snapshot',{});plan=snap.get('study_plan',snap.get('runtime_plan',{}));env=plan.get('environment',plan.get('measurement',{}))
        ps={p['position_hash']:p for p in v.get('positions',[])};planned={p['position_hash']:p for p in v.get('planned_positions',[])}
        revision=v['config'].get('revision','phase35' if 'runtime_plan' in snap else 'Unknown')
        sources=[]
        if v.get('stage_measurements'):
            for r in v['stage_measurements']:
                sources.append({**r,'position_hash':r.get('position_id'),'measurement':'coarse-exclusive-v1','wall':r.get('exclusive_wall_seconds'),'cpu':r.get('exclusive_cpu_seconds'),'complete':r.get('completed',False)})
        else:
            for r in v.get('runtime_measurements',[]):
                sources.append({**r,'stage':'policy_direct','measurement':'detailed-profile' if r.get('instrumented') or r.get('mode')=='Detailed Profile' else 'legacy-direct-v1',
                  'wall':r.get('wall_seconds'),'cpu':r.get('cpu_seconds'),'complete':r.get('measurement_completed',False),**{k:r.get('cost',{}).get(k) if r.get('cost') else None for k in ('derived_games','simulated_turns')}})
            for p in ps.values():
                a=p.get('adaptive',{})
                for r in a.get('research_paths',[]):sources.append({'position_hash':p['position_hash'],'model':r['model'],'stage':'policy_reconstruction','budget':r['budget'],'wall':r.get('cost',{}).get('elapsed_seconds'),'derived_games':r.get('cost',{}).get('derived_games'),'simulated_turns':r.get('cost',{}).get('simulated_turns'),'complete':True,'measurement':'legacy-stage-inclusive-v1'})
                for stage in ('reference','final'):
                    for model,r in a.get(stage,{}).items():sources.append({'position_hash':p['position_hash'],'model':model,'stage':stage,'budget':v['config'].get(stage+'_worlds'),'wall':r.get('cost',{}).get('elapsed_seconds'),'derived_games':r.get('cost',{}).get('derived_games'),'simulated_turns':r.get('cost',{}).get('simulated_turns'),'complete':True,'measurement':'legacy-stage-inclusive-v1'})
        for index,r in enumerate(sources):
            pid=r.get('position_hash');p=ps.get(pid,planned.get(pid,{}));stage='policy' if r.get('stage') in ('policy_direct','policy_reconstruction') else r.get('stage','Unknown')
            legal=ps.get(pid,{}).get('adaptive',{}).get('legal_count');worlds=r.get('budget')
            if r.get('cost'):legal=r['cost'].get('legal_count',legal);worlds=r['cost'].get('hidden_worlds',worlds)
            if stage in ('reference','final'):worlds=v['config'].get(stage+'_worlds')
            if worlds is None and r.get('stage')=='policy_reconstruction':
                path=next((x for x in ps.get(pid,{}).get('adaptive',{}).get('research_paths',[]) if x.get('model')==r.get('model')),{})
                worlds=path.get('budget')
            if r.get('stage')=='policy_direct':
                match=next((x for x in v.get('runtime_measurements',[]) if x.get('position_hash')==pid and x.get('model')==r.get('model') and x.get('method')==r.get('method') and x.get('phase')==r.get('phase')),None)
                if match:worlds=(match.get('cost') or {}).get('hidden_worlds')
            q='使用可能';reasons=[]
            if r['measurement']=='detailed-profile':q='使用不可';reasons=['詳細profileの摂動を含む']
            elif not r['complete']:q='使用不可';reasons=['未完了の計測区間']
            elif r.get('wall') is None or not isfinite(r['wall']) or r['wall']<=0 or not all(k in env for k in ('os','cpu','python')):q='情報不足';reasons=['時間または測定環境が不明']
            elif r['measurement']!='coarse-exclusive-v1':q='条件付き使用可能';reasons=['旧計測は保存等の含有範囲が異なる。記述用として分離']
            elif stage not in ('policy','reference','final'):q='条件付き使用可能';reasons=['管理区間。モデル別探索単価には使用しない']
            elif not r.get('simulated_turns') or legal is None or worlds is None or not r.get('model') or normalized(p.get('period',r.get('period'))) not in PERIODS: q='情報不足';reasons=['手番数または合法手数が不明']
            if revision in ('phase39','phase40') and v['config'].get('stage')=='independent_validation' and q=='使用可能':q='条件付き使用可能';reasons=['独立検証。校正へ逆流させず事後分析のみ']
            if r.get('phase')=='warmup' and q=='使用可能':q='条件付き使用可能';reasons=['warmupは通常区間と別扱い']
            turn=p.get('turn',r.get('turn'));label=normalized(p.get('period',r.get('period'))) or 'Unknown'
            records.append({'record_id':digest({'id':v['id'],'index':index}),'experiment_id':v['id'],'phase':revision,'created_at':v.get('created_at'),
              'environment':{k:env.get(k,'Unknown') for k in ('os','cpu','python')},'measurement':r['measurement'],'quality':q,'reasons':reasons,
              'stage':stage,'physical_stage':r.get('stage'),'model':r.get('model') or 'Unknown','period':label,'turn':turn,'remaining_turns':15-turn if turn is not None else None,
              'deal_hash':p.get('deal_hash',r.get('deal_hash')),'position_hash':pid,'worlds':worlds,'legal_count':legal,
              'derived_games':r.get('derived_games'),'simulated_turns':r.get('simulated_turns'),'wall_seconds':r.get('wall'),'cpu_seconds':r.get('cpu'),
              'written_bytes':r.get('written_bytes'),'transactions':r.get('transactions'),'job_status':v['status'],'interval_complete':r['complete']})
    grouped=defaultdict(list)
    for r in records:
        if r['quality'] in ('使用可能','条件付き使用可能') and r['wall_seconds'] is not None and r['derived_games'] and r['simulated_turns']:
            grouped[(str(sorted(r['environment'].items())),r['measurement'],r['quality'],r['stage'],r['model'],r['period'])].append(r)
    summary=[]
    for key,rs in sorted(grouped.items()):
        summary.append(dict(zip(('environment','measurement','quality','stage','model','period'),key))|{'observations':len(rs),'independent_deals':len({r['deal_hash'] for r in rs if r['deal_hash']}),
          'seconds_per_game':stats([r['wall_seconds']/r['derived_games'] for r in rs]),'seconds_per_turn':stats([r['wall_seconds']/r['simulated_turns'] for r in rs]),
          'wall_intervals':stats([r['wall_seconds'] for r in rs]),'note':'観測件数は区間数。配札数とは異なる。モデル別の総worker時間は共有管理を配分できずUnknown。'})
    return {'records':records,'quality_counts':{k:sum(r['quality']==k for r in records) for k in QUALITY},'summaries':summary,
      'experiments':[{'id':v['id'],'status':v['status'],'elapsed_seconds':v.get('elapsed_seconds'),'environment':v.get('snapshot',{}).get('study_plan',v.get('snapshot',{}).get('runtime_plan',{})).get('environment','Unknown')} for v in jobs],'source_ids':[v['id'] for v in jobs],'missing_condition':'不明値はnull/Unknown。異なる計測方式・環境を一括平均しない。'}

class Cell(BaseModel):
    model_config=ConfigDict(extra='forbid')
    n:int=Field(ge=1);deals:int=Field(ge=1)
    rate:float=Field(gt=0,le=.1,allow_inf_nan=False);slow:float=Field(gt=0,le=.1,allow_inf_nan=False)
    min_legal:int=Field(ge=1,le=17);max_legal:int=Field(ge=1,le=17)
    min_worlds:int=Field(ge=1,le=256);max_worlds:int=Field(ge=1,le=256)
    @model_validator(mode='after')
    def valid(self):
        if self.slow<self.rate or self.min_legal>self.max_legal or self.min_worlds>self.max_worlds:raise ValueError('校正セルの範囲が不正')
        return self

class StorageRates(BaseModel):
    model_config=ConfigDict(extra='forbid')
    benchmark_id:str
    mean_per_write:float=Field(gt=0,le=10,allow_inf_nan=False);max_per_write:float=Field(gt=0,le=10,allow_inf_nan=False)
    history_min:int=Field(ge=0);history_max:int=Field(ge=0)
    payload_min:int=Field(ge=1);payload_max:int=Field(ge=1)
    @model_validator(mode='after')
    def valid(self):
        if self.max_per_write<self.mean_per_write or self.history_max<self.history_min or self.payload_max<self.payload_min:raise ValueError('保存負荷の範囲が不正')
        return self

class CoverageModel(CalibrationModel):
    version:Literal['coverage-turn-rate-v2']='coverage-turn-rate-v2'
    cells:dict[str,Cell]=Field(min_length=1,max_length=36)
    storage:StorageRates
    quality_counts:dict[str,int]
    conservative_management_seconds:float=Field(default=1,ge=1,le=120)

def fit_coverage(jobs,benchmark):
    if any(v['config'].get('stage')=='independent_validation' for v in jobs):raise ValueError('独立検証を同版モデルの校正へ戻しません')
    data=inventory(jobs);rs=[r for r in data['records'] if r['quality']=='使用可能']
    if not rs:raise ValueError('粗粒度の完了した開発区間がありません')
    environments={tuple(r['environment'].items()) for r in rs}
    if len(environments)!=1:raise ValueError('異なる測定環境を混合しません')
    env=dict(next(iter(environments)))
    if benchmark['status']!='Completed' or benchmark['environment']!=env:raise ValueError('同環境の完了した保存ベンチマークが必要')
    groups=defaultdict(list);broad=defaultdict(list)
    for r in rs:
        groups[f"{r['stage']}:{r['model']}:{r['period']}"].append(r);broad[f"{r['stage']}:{r['model']}"].append(r)
    cells={k:Cell(n=len(xs),deals=len({x['deal_hash'] for x in xs}),rate=sum(x['wall_seconds'] for x in xs)/sum(x['simulated_turns'] for x in xs),
      slow=max(x['wall_seconds']/x['simulated_turns'] for x in xs),min_legal=min(x['legal_count'] for x in xs),max_legal=max(x['legal_count'] for x in xs),min_worlds=min(x['worlds'] for x in xs),max_worlds=max(x['worlds'] for x in xs)) for k,xs in groups.items()}
    cases=benchmark['cases'];times=[t for c in cases for t in c['write_seconds']]
    management=[]
    for v in jobs:
        if v['config'].get('stage')=='independent_validation':continue
        b=v.get('cost_breakdown',{});stages=b.get('stages',{})
        if stages:management.append((sum(s['wall_seconds'] for k,s in stages.items() if k in ('collection','position_management','aggregation'))+max(0,b['unmeasured_residual_seconds']))/v['config']['deals'])
    admin=float(np.mean(management)) if management else 1.
    return CoverageModel(source_ids=[v['id'] for v in jobs],source_deal_hashes=sorted({h for v in jobs for h in v['snapshot']['deal_hashes']}),environment=env,
      rates={k:sum(x['wall_seconds'] for x in xs)/sum(x['simulated_turns'] for x in xs) for k,xs in broad.items()},
      slow_rates={k:max(x['wall_seconds']/x['simulated_turns'] for x in xs) for k,xs in broad.items()},cells=cells,
      storage=StorageRates(benchmark_id=benchmark['id'],mean_per_write=float(np.mean(times)),max_per_write=max(times),history_min=min(c['history_rows'] for c in cases),history_max=max(c['history_rows'] for c in cases),payload_min=min(c['payload_bytes'] for c in cases),payload_max=max(c['payload_bytes'] for c in cases)),
      quality_counts=data['quality_counts'],management_seconds=min(60,admin),conservative_management_seconds=min(120,max(1.,max(management,default=1.)*1.5)),
      note='同環境の粗粒度・排他的な開発区間だけ。モデル×時点×処理段階の秒/手番。保存は合成DB単価×実行前書込回数上限。未知セルは全時点のモデル単価へ外挿し警告。安全係数1.5は信頼水準ではない。')

def forecast_coverage(c,estimate):
    m=c.calibration;slots=[];warnings=[]
    if c.warmups:raise ValueError('v2予測はwarmupなしのみ')
    active=[p for p in PERIODS if any(normalized(period(t))==p for t in c.turns)]
    for i in range(c.deals):
        p=active[i%len(active)];ts=[t for t in c.turns if normalized(period(t))==p];k=17-min(ts);remaining=15-min(ts)
        mean=slow=0.;components=[]
        for stage,worlds in (('policy',512),('reference',c.reference_worlds),('final',c.final_worlds)):
            for model in c.models:
                key=f'{stage}:{model}:{p}';cell=m.cells.get(key);rate=cell.rate if cell else m.rates[stage+':'+model];high=cell.slow if cell else m.slow_rates[stage+':'+model]
                observed_worlds=128 if stage=='policy' else worlds
                if cell is None:warnings.append('未観測セル:'+key)
                elif not cell.min_legal<=k<=cell.max_legal or not cell.min_worlds<=observed_worlds<=cell.max_worlds:warnings.append('合法手/世界数の外挿:'+key)
                units=k*remaining*worlds;mean+=rate*units;slow+=high*units*m.safety_factor
                components.append({'stage':stage,'model':model,'turns_upper':units,'rate':rate,'conservative_rate':high*m.safety_factor})
        slots.append({'ordinal':i,'period':p,'predicted_search_seconds':mean,'conservative_search_seconds':slow,'components':components})
    writes=ceil(c.timeout_seconds/.25)+c.deals*len(c.models)*3+c.deals+8
    if c.warmups:warnings.append('warmupはv2適用範囲外')
    if c.storage_history_rows is None or c.expected_payload_bytes is None:warnings.append('保存条件が不明')
    else:
        if not m.storage.history_min<=c.storage_history_rows<=m.storage.history_max:warnings.append('履歴件数が校正範囲外')
        if not m.storage.payload_min<=c.expected_payload_bytes<=m.storage.payload_max:warnings.append('payload量が校正範囲外')
    mean=sum(s['predicted_search_seconds'] for s in slots)+m.management_seconds*c.deals+m.storage.mean_per_write*writes
    slow=sum(s['conservative_search_seconds'] for s in slots)+m.conservative_management_seconds*c.deals+m.storage.max_per_write*writes*m.safety_factor
    return {'model_hash':digest(m.model_dump(mode='json')),'source_ids':m.source_ids,'model_version':m.version,'predicted_seconds':mean,'conservative_seconds':slow,
      'derived_games_upper':estimate['derived_games_upper'],'simulated_turns_upper':sum(x['turns_upper'] for s in slots for x in s['components']),
      'storage_writes_upper':writes,'slots':slots,'timeout_seconds':c.timeout_seconds,'coverage_status':('情報不足' if c.storage_history_rows is None or c.expected_payload_bytes is None else '範囲外' if not any(f'{st}:{mo}:{p}' in m.cells for st in ('policy','reference','final') for mo in c.models for p in active) else '一部範囲外' if warnings else '適用範囲内'),
      'warnings':sorted(set(warnings)),'rating':'予算内の見込み' if slow<=c.timeout_seconds else '予算超過のおそれ','reliability':'低い。少数配札・各セルの最大値であり保証ではない。',
      'scope':m.note,'storage_assumption':'単価×実行前の最大書込数。合成ベンチマークの保存回数/管理イベントと実workerの.25秒間隔は同一分布とは保証しない。',
      'guarantee':False}

def validate_forecast(v):
    frozen=v['snapshot']['study_plan']['completion_forecast'];by=defaultdict(float)
    for r in v.get('stage_measurements',[]):
        if r['stage'] in ('policy_reconstruction','policy_direct','reference','final') and r.get('exclusive_wall_seconds') is not None:by[r['position_id']]+=r['exclusive_wall_seconds']
    done={p['position_hash'] for p in v['positions']};rows=[]
    planned=v.get('planned_positions',[])
    if len(planned)>len(frozen['slots']) or len({p['deal_hash'] for p in planned})!=len(planned):raise ValueError('固定枠と1配札1局面が不一致')
    for index,p in enumerate(v.get('planned_positions',[])):
        pred=frozen['slots'][index];actual=by.get(p['position_hash'])
        rows.append({'deal_hash':p['deal_hash'],'position_hash':p['position_hash'],'period':p['period'],'complete':p['position_hash'] in done,
          'predicted_search_seconds':pred['predicted_search_seconds'],'conservative_search_seconds':pred['conservative_search_seconds'],
          'actual_search_seconds':actual,'absolute_error':abs(actual-pred['predicted_search_seconds']) if actual is not None else None,
          'signed_relative_error':(actual-pred['predicted_search_seconds'])/pred['predicted_search_seconds'] if actual is not None else None,
          'conservative_actual_ratio':pred['conservative_search_seconds']/actual if actual else None,
          'conservative_exceeded':actual>pred['conservative_search_seconds'] if actual is not None and p['position_hash'] in done else None})
    eligible=[r for r in rows if r['complete'] and r['actual_search_seconds'] is not None]
    if len({r['deal_hash'] for r in rows})!=len(rows):raise ValueError('v2検証は1配札1局面のみ')
    return {'deals':rows,'independent_deals':len({r['deal_hash'] for r in eligible}),'exceedances':sum(r['conservative_exceeded'] for r in eligible),
      'exceedance_rate':float(np.mean([r['conservative_exceeded'] for r in eligible])) if eligible and v['status']=='Completed' else None,
      'plan_completed':v['status']=='Completed','mean_absolute_error':float(np.mean([r['absolute_error'] for r in eligible])) if eligible and v['status']=='Completed' else None,
      'scope':'配札の探索部分のみを同じ対象で比較。共有の収集/保存/管理は全体予測で別評価。局面/モデルを独立標本に数えない。',
      'storage_observed':{'writes':sum(r['stage']=='sqlite_json_write' for r in v.get('stage_measurements',[])),
        'written_bytes':sum(r.get('written_bytes',0) for r in v.get('stage_measurements',[])),
        'max_payload_bytes':max((r.get('written_bytes',0) for r in v.get('stage_measurements',[])),default=0)},
      'warning':'少数配札の超過0は保証ではない。未完了時の完了部分は選択バイアスを持ち得る。'}
