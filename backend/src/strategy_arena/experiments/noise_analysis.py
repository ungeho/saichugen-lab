"""時間反復と判断分岐を分離。既存select／再構成／三標本を再利用する。"""
from collections import defaultdict
from contextlib import contextmanager
from copy import deepcopy
from random import Random
from time import perf_counter,perf_counter_ns,process_time
from datetime import datetime,timezone
import sys
import numpy as np
from .adaptive_analysis import METHODS,select,stopping,selection_observer,execution_meter
from .horizon_analysis import analyze_horizon,reconstruct,horizon_summary,KEYS
from .runtime_analysis import assert_same,stringify_stages,seed_strings,runtime_sink,environment
from .runner import derived_seed

@contextmanager
def stopping_meter(enabled):
    """現在workerスレッドだけのprofile。計測群のwallは摂動を含み通常群と別集約。"""
    meter={'calls':0,'seconds':None}
    if not enabled:yield meter;return
    previous=sys.getprofile()
    if previous is not None:raise ValueError('既存profileを上書きしません')
    entered={};total=[0]
    def callback(frame,event,arg):
        if frame.f_code is not stopping.__code__:return
        if event=='call':entered[id(frame)]=perf_counter_ns()
        elif event=='return':
            start=entered.pop(id(frame),None)
            if start is not None:total[0]+=perf_counter_ns()-start;meter['calls']+=1
    sys.setprofile(callback)
    try:yield meter
    finally:
        sys.setprofile(previous);meter['seconds']=total[0]/1e9

def noise_order(c,pid,model,iteration,budget,phase):
    conditions=[(m,instrumented) for m in METHODS for instrumented in ([False,True] if c.measure_stopping else [False])]
    Random(derived_seed(c.order_seed,f'noise-order-v1:{pid}:{model}:{phase}:{iteration}:{budget}')).shuffle(conditions)
    return conditions

def stats(values):
    x=np.asarray(values,dtype=float);n=len(x)
    if not n:return {'n':0,'mean':None,'median':None,'min':None,'max':None,'sd':None,'iqr':None,'cv':None}
    mean=float(np.mean(x));sd=float(np.std(x,ddof=1)) if n>1 else None
    return {'n':n,'mean':mean,'median':float(np.median(x)),'min':float(np.min(x)),'max':float(np.max(x)),
      'sd':sd,'iqr':float(np.quantile(x,.75)-np.quantile(x,.25)),'cv':sd/mean if sd is not None and mean>0 else None}

def analyze_noise(obs,c,pid,check=lambda:None,progress=lambda:None):
    start=perf_counter();cards=obs.legal_actions;sink=runtime_sink.get();meter=execution_meter.get();records=[];paths=[]
    root=derived_seed(c.policy_seed,f'adaptive-v1:{pid}:policy');seed=derived_seed(root,'repeat:0')
    if meter:meter['stage']='policy'
    token=selection_observer.set(None)
    try:
        for model in c.models:
            path=select(obs,cards,model,seed,max(c.budgets),'Fixed',c,check,progress);path['repeat']=0;paths.append(path)
            for budget in c.budgets:
                expected={m:reconstruct(obs,path,budget,m,c) for m in METHODS}
                for phase,count in (('warmup',c.warmups),('measurement',c.measurement_repeats)):
                    for iteration in range(count):
                        order=noise_order(c,pid,model,iteration,budget,phase)
                        for index,(method,instrumented) in enumerate(order):
                            check();entry={'position_hash':pid,'series':'R','phase':phase,'iteration':iteration,'repeat':0,
                              'model':model,'budget':budget,'method':method,'seed':str(seed),'instrumented':instrumented,
                              'execution_order':[{'method':m,'instrumented':i} for m,i in order],'order_index':index,
                              'measured_at':datetime.now(timezone.utc).isoformat(),'measurement_completed':False,
                              'wall_seconds':None,'cpu_seconds':None,'stop_check_seconds':None,'stop_check_count':None,
                              'stop_fraction':None,'classification':'in_progress','cost':None,'path_matches':None}
                            records.append(entry)
                            if sink:sink(entry) # 保存は計時前。
                            cpu=process_time();wall=perf_counter()
                            with stopping_meter(instrumented) as sm:
                                d=select(obs,cards,model,seed,budget,method,c,check,lambda:None)
                            wall=perf_counter()-wall;cpu=process_time()-cpu
                            assert_same(d,expected[method])
                            entry.update(measurement_completed=True,wall_seconds=wall,cpu_seconds=cpu,
                              stop_check_seconds=sm['seconds'],stop_check_count=len(d['trace']),
                              profiled_calls=sm['calls'] if instrumented else None,
                              stop_fraction=sm['seconds']/wall if sm['seconds'] is not None and wall>0 else None,
                              selected_card=d['selected_card'],stop_reason=d['stop_reason'],classification=expected[method]['classification'],
                              cost={**d['cost'],'elapsed_seconds':wall},path_matches=True,trace=d['trace'])
                            if instrumented and sm['calls']!=len(d['trace']):raise ValueError('停止判定計測の呼出数が不一致')
                            progress() # 保存は計時外。
        for r in records:
            f=next(x for x in records if (x['model'],x['budget'],x['phase'],x['iteration'],x['instrumented'],x['method'])==(r['model'],r['budget'],r['phase'],r['iteration'],r['instrumented'],'Fixed'))
            r['wall_difference']=r['wall_seconds']-f['wall_seconds'];r['cpu_difference']=r['cpu_seconds']-f['cpu_seconds']
    finally:selection_observer.reset(token)
    def sumcost(items):return {k:sum(x[k] for x in items) for k in KEYS}
    pathcost=sumcost([p['cost'] for p in paths]);warm=sumcost([r['cost'] for r in records if r['phase']=='warmup']);measured=sumcost([r['cost'] for r in records if r['phase']=='measurement'])
    total={k:pathcost[k]+warm[k]+measured[k] for k in KEYS};zeros={k:0 for k in KEYS}
    return {'series':'R','noise_records':records,'research_paths':seed_strings(paths),'rows':[],
      'stage_seeds':{'policy':str(root)},'legal_count':len(cards),'selection_cost':total,'overhead_cost':zeros,'total_cost':total,
      'reconstruction_cost':pathcost,'warmup_cost':warm,'measurement_cost':measured,'actual_research_compute_cost':total,
      'elapsed_seconds':perf_counter()-start,'scope':'同一seed・同一探索量の測定反復。独立配札数を増やさない。計測群／通常群を別集約。参照／最終評価はSeries Rでは未実施。'}

def analyze_divergence(obs,c,pid,check=lambda:None,progress=lambda:None):
    a=analyze_horizon(obs,c,pid,check,progress);a['series']='D'
    for r in a['rows']:
        e=r['evaluations'][0];different=r['selected_card']!=r['fixed_horizon_card']
        r['decision_divergence']={'diverged':different,'adaptive_card':r['selected_card'],'fixed_card':r['fixed_horizon_card'],
          'selection_seed':str(r['seed']),'adaptive_worlds':r['cost']['hidden_worlds'],'fixed_worlds':r['budget'],
          'first_changed_worlds':next((t['worlds'] for t in r['post_stop_fixed_changes']),None),
          'independent_reward_difference':e['minus_fixed']['mean'],'stop_reason':r['stop_reason'],
          'stop_gap':r['trace'][-1]['gap'],'stop_paired_se':r['trace'][-1]['paired_se'],
          'legal_count':len(obs.legal_actions),'remaining_turns':15-obs.turn}
    return stringify_stages(a)

def study_summary(positions):
    if not positions:return []
    if positions[0]['adaptive']['series']=='D':
        rows=horizon_summary(positions)
        for r in rows:r.update(series='D',divergence_rate=1-r['matches_fixed'],analysis_role='primary' if r['budget']==128 and r['method']!='Fixed' and r['stratum']=='all' else 'secondary',denominator='全事前評価局面。反復→局面→独立配札平均。分岐例だけで選別しない。')
        return rows
    buckets=defaultdict(list)
    for p in positions:
        for r in p['adaptive']['noise_records']:
            if r['phase']=='measurement':buckets[(p['position_hash'],r['model'],r['budget'],r['method'],r['instrumented'])].append((p,r))
    out=[]
    for (pid,model,budget,method,instrumented),items in buckets.items():
        p=items[0][0];rs=[r for _,r in items]
        if len({(r['seed'],r['cost']['derived_games'],r['cost']['simulated_turns'],str(r['selected_card'])) for r in rs})!=1:raise ValueError('Series Rで同一入力／探索量が崩れました')
        out.append({'series':'R','position_hash':pid,'deal_hash':p['deal_hash'],'independent_deals':1,'model':model,'budget':budget,'method':method,'instrumented':instrumented,
          'wall':stats([r['wall_seconds'] for r in rs]),'cpu':stats([r['cpu_seconds'] for r in rs]),
          'wall_difference':stats([r['wall_difference'] for r in rs]),'stop_time':stats([r['stop_check_seconds'] for r in rs if r['stop_check_seconds'] is not None]),
          'stop_fraction':stats([r['stop_fraction'] for r in rs if r['stop_fraction'] is not None]),
          'derived_games':rs[0]['cost']['derived_games'],'simulated_turns':rs[0]['cost']['simulated_turns'],
          'worlds':rs[0]['cost']['hidden_worlds'],'selected_card':rs[0]['selected_card'],
          'scope':'測定反復の記述分布。配札数として扱わず、計測モード／局面を合算しない。'})
    return out
