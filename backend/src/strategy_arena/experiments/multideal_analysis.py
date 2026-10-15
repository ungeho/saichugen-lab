"""固定Planの三標本評価と低負荷直接計時。停止規則は既存selectを使用。"""
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from random import Random
from time import perf_counter, process_time
import numpy as np
from .adaptive_analysis import METHODS, select, selection_observer, execution_meter
from .horizon_analysis import KEYS, reconstruct
from .noise_analysis import analyze_divergence, stats
from .lightweight_analysis import coverage_summary
from .runtime_analysis import runtime_sink, assert_same, seed_strings
from .runner import derived_seed


def method_order(c, model, ordinal):
    order=list(METHODS)
    Random(derived_seed(c.order_seed, 'multideal-order-v1:'+model)).shuffle(order)
    shift=ordinal%3
    return order[shift:]+order[:shift]


def analyze_multideal(obs,c,pid,ordinal,check=lambda:None,progress=lambda:None):
    started=perf_counter()
    a=analyze_divergence(obs,c,pid,check,progress)
    original=deepcopy(a['selection_cost']);costs=[];records=[]
    sink=runtime_sink.get();meter=execution_meter.get()
    token=selection_observer.set(None)
    try:
        if meter:meter['stage']='policy'
        for model in c.models:
            path=next(p for p in a['research_paths'] if p['model']==model)
            order=method_order(c,model,ordinal)
            phases=[('warmup',16)]*c.warmups if ordinal==0 else []
            phases += [('measurement',128)]
            for phase,budget in phases:
                for index,method in enumerate(order):
                    expected=next(r for r in a['rows'] if r['model']==model and r['method']==method) if phase=='measurement' else reconstruct(obs,path,budget,method,c)
                    record={'position_hash':pid,'model':model,'repeat':0,'budget':budget,'method':method,'mode':'Lightweight',
                      'phase':phase,'ordinal':ordinal,'seed':str(path['seed']),'execution_order':order,'order_index':index,
                      'measured_at':datetime.now(timezone.utc).isoformat(),'measurement_completed':False,
                      'wall_seconds':None,'cpu_seconds':None,'stop_check_seconds':None,'stop_check_count':None,'cost':None,'classification':'in_progress'}
                    records.append(record)
                    check()
                    if sink:sink(record)
                    count=[0]
                    def observer(meta,event,value):
                        if event=='checkpoint':count[0]+=1
                    cpu=process_time();wall=perf_counter()
                    inner=selection_observer.set(observer)
                    try:d=select(obs,obs.legal_actions,model,int(path['seed']),budget,method,c,check,lambda:None)
                    finally:selection_observer.reset(inner)
                    wall=perf_counter()-wall;cpu=process_time()-cpu
                    assert_same(d,expected)
                    if count[0]!=len(d['trace']):raise ValueError('低負荷判定回数が不一致')
                    dc={**d['cost'],'elapsed_seconds':wall};costs.append((phase,dc))
                    record.update(measurement_completed=True,wall_seconds=wall,cpu_seconds=cpu,stop_check_count=count[0],cost=dc,
                      selected_card=d['selected_card'],stop_reason=d['stop_reason'],classification=expected['classification'],path_matches=True)
                    if phase=='measurement':expected['direct_measurement']=record
                    progress()
        for r in a['rows']:
            f=next(x for x in a['rows'] if x['model']==r['model'] and x['method']=='Fixed')
            for key in ('wall','cpu'):
                r['direct_measurement'][key+'_difference']=r['direct_measurement'][key+'_seconds']-f['direct_measurement'][key+'_seconds']
    finally:selection_observer.reset(token)
    direct={k:sum(d[k] for _,d in costs) for k in KEYS}
    selection={k:original[k]+direct[k] for k in KEYS}
    total={k:selection[k]+a['overhead_cost'][k] for k in KEYS}
    a.update(revision='phase38',selection_cost=selection,total_cost=total,actual_research_compute_cost=total,
      reconstruction_cost=original,direct_execution_cost={k:sum(d[k] for phase,d in costs if phase=='measurement') for k in KEYS},
      warmup_cost={k:sum(d[k] for phase,d in costs if phase=='warmup') for k in KEYS},noise_records=records,
      elapsed_seconds=perf_counter()-started,scope='固定Plan。三標本は独立、直接実時間はLightweight。保存・参照・最終評価は計時外。')
    return seed_strings(a)


def multideal_summary(positions):
    out=coverage_summary(positions)
    for r in out:
        grouped=defaultdict(lambda:defaultdict(list));signs={'positive':0,'negative':0,'zero':0}
        for p in positions:
            labels=('all',p['period'],p['stratum']['class'],'source:'+p['source'],f'legal:{p["adaptive"]["legal_count"]}',f'remaining:{15-p["turn"]}')
            if r['stratum'] not in labels:continue
            for row in p['adaptive']['rows']:
                if (row['method'],row['model'],row['budget'])!=(r['method'],r['model'],r['budget']):continue
                m=row['direct_measurement'];e=row['evaluations'][0]
                grouped[p['deal_hash']][p['position_hash']].append({k:m[k] for k in ('wall_seconds','cpu_seconds','wall_difference','cpu_difference')}|{'reward_difference':e['minus_fixed']['mean']})
                if row['decision_divergence']['diverged']:
                    v=e['minus_fixed']['mean'];signs['positive' if v>0 else 'negative' if v<0 else 'zero']+=1
        ds=[{'deal_hash':dh,**{k:float(np.mean([np.mean([v[k] for v in xs]) for xs in ps.values()])) for k in ('wall_seconds','cpu_seconds','wall_difference','cpu_difference','reward_difference')}} for dh,ps in sorted(grouped.items())]
        r.update(revision='phase38',paired_deals=ds,divergent_reward_signs=signs,
          wall_difference=stats([d['wall_difference'] for d in ds]),cpu_difference=stats([d['cpu_difference'] for d in ds]),
          wall_seconds=stats([d['wall_seconds'] for d in ds]),wall_difference_interval=None,
          analysis_role='secondary_exploratory',time_uncertainty='独立配札単位の記述。小標本・環境ノイズのため時間CIなし。')
    # 主比較は事前固定した3モデルを同一配札内で等重み。モデルを独立標本に数えない。
    for method in METHODS[1:]:
        rows=[r for r in out if r['stratum']=='all' and r['method']==method]
        if not rows:continue
        deals=defaultdict(list)
        for r in rows:
            for d in r['paired_deals']:deals[d['deal_hash']].append(d)
        paired=[{'deal_hash':dh,**{k:float(np.mean([x[k] for x in xs])) for k in ('wall_difference','cpu_difference','reward_difference')}} for dh,xs in sorted(deals.items())]
        out.append({'series':'D','revision':'phase38','stratum':'primary_equal_models','method':method,'model':'equal-models','budget':128,
          'analysis_role':'primary','independent_deals':len(paired),'paired_deals':paired,
          'wall_difference':stats([d['wall_difference'] for d in paired]),'reward_difference':float(np.mean([d['reward_difference'] for d in paired])),
          'wall_difference_interval':None,'reward_difference_interval':None,'uncertainty':'小標本の記述のみ。同等性・性能維持の証明ではない。'})
    return out
