"""Phase 37：チェックポイント計数だけの低負荷計測と独立配札の分岐集約。"""
from collections import defaultdict
from copy import deepcopy
from datetime import datetime,timezone
from random import Random
from time import perf_counter,process_time
from .adaptive_analysis import METHODS,select,selection_observer,execution_meter
from .horizon_analysis import reconstruct,KEYS
from .noise_analysis import stopping_meter,stats,study_summary,analyze_divergence
from .runtime_analysis import runtime_sink,assert_same,seed_strings
from .runner import derived_seed

MODES=('Baseline','Lightweight','Detailed Profile')

def balanced_order(c,pid,model,iteration,budget,phase):
    rng=Random(derived_seed(c.order_seed,f'balanced-runtime-v1:{pid}:{model}:{budget}:{phase}'))
    methods=list(METHODS);modes=list(c.measurement_modes);rng.shuffle(methods);rng.shuffle(modes)
    methods=methods[iteration%3:]+methods[:iteration%3]
    output=[]
    for method in methods:
        # 元の方式番号を使い、方式群の位置と群内modeの両方を循環させる。
        shift=(iteration//3+METHODS.index(method))%len(modes)
        output.extend((method,m) for m in modes[shift:]+modes[:shift])
    return output

def analyze_lightweight(obs,c,pid,check=lambda:None,progress=lambda:None):
    started=perf_counter();cards=obs.legal_actions;sink=runtime_sink.get();meter=execution_meter.get();records=[];paths=[]
    root=derived_seed(c.policy_seed,f'adaptive-v1:{pid}:policy');seed=derived_seed(root,'repeat:0')
    if meter:meter['stage']='policy'
    outer=selection_observer.set(None)
    try:
        for model in c.models:
            path=select(obs,cards,model,seed,max(c.budgets),'Fixed',c,check,progress);path['repeat']=0;paths.append(path)
            for budget in c.budgets:
                expected={m:reconstruct(obs,path,budget,m,c) for m in METHODS}
                for phase,count in (('warmup',c.warmups),('measurement',c.measurement_repeats)):
                    for iteration in range(count):
                        order=balanced_order(c,pid,model,iteration,budget,phase)
                        for order_index,(method,mode) in enumerate(order):
                            check();entry={'position_hash':pid,'series':'R','phase':phase,'iteration':iteration,'repeat':0,
                              'model':model,'budget':budget,'method':method,'seed':str(seed),'mode':mode,'instrumented':mode=='Detailed Profile',
                              'execution_order':[{'method':m,'mode':k} for m,k in order],'order_index':order_index,
                              'measured_at':datetime.now(timezone.utc).isoformat(),'measurement_completed':False,
                              'wall_seconds':None,'cpu_seconds':None,'stop_check_seconds':None,'stop_check_count':None,
                              'stop_fraction':None,'classification':'in_progress','cost':None,'path_matches':None}
                            records.append(entry)
                            if sink:sink(entry)
                            counts=[0]
                            def observer(meta,event,value):
                                if event=='checkpoint':counts[0]+=1
                            cpu=process_time();wall=perf_counter()
                            token=selection_observer.set(observer if mode=='Lightweight' else None)
                            try:
                                with stopping_meter(mode=='Detailed Profile') as sm:
                                    d=select(obs,cards,model,seed,budget,method,c,check,lambda:None)
                            finally:selection_observer.reset(token)
                            wall=perf_counter()-wall;cpu=process_time()-cpu
                            assert_same(d,expected[method])
                            if mode=='Lightweight' and counts[0]!=len(d['trace']):raise ValueError('低負荷チェックポイント数が不一致')
                            if mode=='Detailed Profile' and sm['calls']!=len(d['trace']):raise ValueError('詳細判定回数が不一致')
                            entry.update(measurement_completed=True,wall_seconds=wall,cpu_seconds=cpu,
                              stop_check_seconds=sm['seconds'],stop_check_count=len(d['trace']),
                              lightweight_checkpoints=counts[0] if mode=='Lightweight' else None,
                              profiled_calls=sm['calls'] if mode=='Detailed Profile' else None,
                              stop_fraction=sm['seconds']/wall if sm['seconds'] is not None and wall>0 else None,
                              selected_card=d['selected_card'],stop_reason=d['stop_reason'],classification=expected[method]['classification'],
                              cost={**d['cost'],'elapsed_seconds':wall},path_matches=True,trace=d['trace'])
                            progress()
        for r in records:
            b=next(x for x in records if (x['model'],x['budget'],x['phase'],x['iteration'],x['method'],x['mode'])==(r['model'],r['budget'],r['phase'],r['iteration'],r['method'],'Baseline'))
            f=next(x for x in records if (x['model'],x['budget'],x['phase'],x['iteration'],x['method'],x['mode'])==(r['model'],r['budget'],r['phase'],r['iteration'],'Fixed',r['mode']))
            diff=r['wall_seconds']-b['wall_seconds']
            r.update(baseline_wall_difference=diff,baseline_wall_absolute_difference=abs(diff),
              baseline_wall_relative_difference=diff/b['wall_seconds'] if b['wall_seconds']>0 else None,
              baseline_cpu_difference=r['cpu_seconds']-b['cpu_seconds'],wall_difference=r['wall_seconds']-f['wall_seconds'],
              baseline_same_result=r['selected_card']==b['selected_card'],baseline_same_cost=r['cost']['derived_games']==b['cost']['derived_games'] and r['cost']['simulated_turns']==b['cost']['simulated_turns'])
    finally:selection_observer.reset(outer)
    def sumcost(xs):return {k:sum(x[k] for x in xs) for k in KEYS}
    pathcost=sumcost([p['cost'] for p in paths]);warm=sumcost([r['cost'] for r in records if r['phase']=='warmup']);measured=sumcost([r['cost'] for r in records if r['phase']=='measurement'])
    total={k:pathcost[k]+warm[k]+measured[k] for k in KEYS}
    return {'series':'R','revision':'phase37','noise_records':records,'research_paths':seed_strings(paths),'rows':[],
      'stage_seeds':{'policy':str(root)},'legal_count':len(cards),'selection_cost':total,'overhead_cost':{k:0 for k in KEYS},'total_cost':total,
      'reconstruction_cost':pathcost,'warmup_cost':warm,'measurement_cost':measured,'actual_research_compute_cost':total,
      'elapsed_seconds':perf_counter()-started,'scope':'BaselineとLightweightは同じ外側wall/CPUタイマー。LWはcheckpoint計数だけ。摂動差は環境ノイズも含む。'}

def lightweight_summary(positions):
    if not positions:return []
    if positions[0]['adaptive']['series']=='D':return coverage_summary(positions)
    grouped=defaultdict(list)
    for p in positions:
        for r in p['adaptive']['noise_records']:
            if r['phase']=='measurement':grouped[(p['position_hash'],r['model'],r['budget'],r['method'],r['mode'])].append((p,r))
    out=[]
    for (pid,model,budget,method,mode),items in grouped.items():
        p=items[0][0];rs=[x for _,x in items]
        if len({(x['seed'],x['cost']['derived_games'],x['cost']['simulated_turns'],str(x['selected_card'])) for x in rs})!=1:raise ValueError('同一入力の反復条件が不一致')
        out.append({'series':'R','revision':'phase37','position_hash':pid,'deal_hash':p['deal_hash'],'independent_deals':1,'model':model,'budget':budget,'method':method,'mode':mode,'instrumented':mode=='Detailed Profile',
          'wall':stats([x['wall_seconds'] for x in rs]),'cpu':stats([x['cpu_seconds'] for x in rs]),'wall_difference':stats([x['wall_difference'] for x in rs]),
          'baseline_difference':stats([x['baseline_wall_difference'] for x in rs]),'baseline_absolute_difference':stats([x['baseline_wall_absolute_difference'] for x in rs]),
          'baseline_relative_difference':stats([x['baseline_wall_relative_difference'] for x in rs if x['baseline_wall_relative_difference'] is not None]),
          'stop_time':stats([x['stop_check_seconds'] for x in rs if x['stop_check_seconds'] is not None]),'stop_fraction':stats([x['stop_fraction'] for x in rs if x['stop_fraction'] is not None]),
          'same_result':all(x['baseline_same_result'] for x in rs),'same_cost':all(x['baseline_same_cost'] for x in rs),
          'worlds':rs[0]['cost']['hidden_worlds'],'derived_games':rs[0]['cost']['derived_games'],'simulated_turns':rs[0]['cost']['simulated_turns'],'selected_card':rs[0]['selected_card']})
    return out

def coverage_summary(positions):
    rows=study_summary(positions)
    for source in ('Random','Heuristic','ScoreAware','Zigzag','Reverse Zigzag'):
        for r in study_summary([p for p in positions if p['source']==source]):
            if r.get('stratum')=='all':rows.append({**r,'stratum':'source:'+source})
    for r in rows:
        deals=defaultdict(lambda:defaultdict(list))
        for p in positions:
            labels=('all',p['stratum']['class'],p['period'],f'legal:{p["adaptive"]["legal_count"]}',f'remaining:{15-p["turn"]}','source:'+p['source'])
            if r['stratum'] not in labels:continue
            for row in p['adaptive']['rows']:
                if (row['model'],row['method'],row['budget'])==(r['model'],r['method'],r['budget']):deals[p['deal_hash']][p['position_hash']].append(row['decision_divergence']['diverged'])
        detail=[{'deal_hash':dh,'positions':len(ps),'decisions':sum(len(xs) for xs in ps.values()),'divergent_decisions':sum(sum(xs) for xs in ps.values()),
          'any_divergence':any(any(xs) for xs in ps.values()),'rate':float(sum(sum(xs)/len(xs) for xs in ps.values())/len(ps))} for dh,ps in sorted(deals.items())]
        n=len(detail);events=sum(x['any_divergence'] for x in detail)
        r.update(revision='phase37',deal_events=detail,deal_event_count=events,raw_decisions=sum(x['decisions'] for x in detail),
          raw_divergent_decisions=sum(x['divergent_decisions'] for x in detail),event_interval=None,
          uncertainty='少数独立配札のため区間未提示。モデル・局面・反復を独立な二項試行としない。',
          miss_scenarios=[{'assumed_deal_event_probability':p,'zero_events_probability':(1-p)**n,'assumption':'各独立配札の発生確率が同じpの場合の仮定例。推定区間・実際の頻度ではない。'} for p in (.1,.25,.5)] if n and events==0 and r['method']!='Fixed' else [])
    return rows
