"""既存選択を直接計時。再構成との差異を拒否し、独立評価だけを共有する。"""
from collections import defaultdict
from contextvars import ContextVar
from copy import deepcopy
from random import Random
from time import perf_counter,process_time
import os,platform,sys
import numpy as np
from .adaptive_analysis import METHODS,select,selection_observer,execution_meter
from .horizon_analysis import analyze_horizon,horizon_summary,KEYS
from .stopping_analysis import trace_sink
from .runner import derived_seed

runtime_sink=ContextVar('runtime_measurement_sink',default=None)

def seed_strings(value,key=''):
    """新Labの全seedは十進文字列。旧LabのJSON／Hashは変更しない。"""
    if key=='stage_seeds' and isinstance(value,dict):return {k:str(v) for k,v in value.items()}
    if isinstance(value,dict):return {k:seed_strings(v,k) for k,v in value.items()}
    if isinstance(value,list):return [seed_strings(v,key) for v in value]
    if isinstance(value,int) and not isinstance(value,bool) and ('seed' in key):return str(value)
    return value

def stringify_stages(a):
    out=seed_strings(a);out['stage_seeds']={k:str(v) for k,v in a['stage_seeds'].items()};return out

def environment(c):
    return {'python':sys.version,'os':platform.platform(),'cpu':platform.processor(),'processes':1,'workers':1,
      'parallel':False,'logical_cpu_count':os.cpu_count(),'wall_timer':'time.perf_counter','cpu_timer':'time.process_time',
      'warmup':False,'prior_computation':'専用ウォームアップなし。照合用経路・参照・最終評価を先に計算するためキャッシュは温まり得る。','measurement_repeats':c.repeats,'order_seed':str(c.order_seed),
      'scope':'select呼出直前から選択結果返却まで。世界生成・軽量戦略初期化・候補評価・停止判定・通常トレース構築を含む。DB・収集・参照・最終評価・JSON・UIは除外。',
      'cpu_scope':'単一workerのプロセスCPU。別Lab並行稼働など他スレッドの影響は排除できない。',
      'stop_check_seconds':None,'stop_check_scope':'停止関数だけの時間分離は未実装。0とは扱わない。'}

def execution_order(c,pid,model,repeat,budget):
    order=list(METHODS);Random(derived_seed(c.order_seed,f'runtime-order-v1:{pid}:{model}:{repeat}:{budget}')).shuffle(order);return order

def assert_same(direct,reconstructed):
    for key in ('selected_card','stop_reason','early_stop','max_budget_reached'):
        if direct[key]!=reconstructed[key]:raise ValueError('直接実行／再構成が不一致: '+key)
    for key in ('hidden_worlds','derived_games','simulated_turns','simulated_player_actions'):
        if direct['cost'][key]!=reconstructed['cost'][key]:raise ValueError('直接実行／再構成コストが不一致: '+key)
    if direct['candidates']!=reconstructed['candidates']:raise ValueError('候補評価が不一致')

def analyze_runtime(obs,c,pid,check=lambda:None,progress=lambda:None):
    # 最初の最大Fixed経路と独立評価は計時の外。後続情報はselectへ渡さない。
    started=perf_counter();a=analyze_horizon(obs,c,pid,check,progress);research_selection=deepcopy(a['selection_cost']);direct_costs=[]
    sink=runtime_sink.get();meter=execution_meter.get();token=selection_observer.set(None)
    try:
        if meter:meter['stage']='policy'
        for model in c.models:
            for repeat in range(c.repeats):
                for budget in c.budgets:
                    order=execution_order(c,pid,model,repeat,budget)
                    for order_index,method in enumerate(order):
                        r=next(r for r in a['rows'] if r['model']==model and r['repeat']==repeat and r['budget']==budget and r['method']==method)
                        record={'position_hash':pid,'model':model,'repeat':repeat,'budget':budget,'method':method,
                          'seed':str(r['seed']),'execution_order':order,'order_index':order_index,'measurement_completed':False,
                          'wall_seconds':None,'cpu_seconds':None,'stop_check_seconds':None,'stop_check_count':None,
                          'classification':'in_progress','cost':None,'path_matches':None}
                        if sink:sink(record)
                        check();cpu_start=process_time();wall_start=perf_counter()
                        d=select(obs,obs.legal_actions,model,r['seed'],budget,method,c,check,lambda:None)
                        wall=perf_counter()-wall_start;cpu=process_time()-cpu_start
                        assert_same(d,r)
                        dc={**d['cost'],'elapsed_seconds':wall};direct_costs.append(dc)
                        record.update(measurement_completed=True,wall_seconds=wall,cpu_seconds=cpu,stop_check_count=len(d['trace']),
                          classification=r['classification'],selected_card=d['selected_card'],stop_reason=d['stop_reason'],
                          cost=dc,path_matches=True)
                        r['direct_measurement']=record
                        r['post_stop_analysis']={'first_changed_worlds':next((x['worlds'] for x in r['post_stop_fixed_changes']),None),
                          'additional_games_to_horizon':len(obs.legal_actions)*(budget-d['cost']['hidden_worlds']),
                          'additional_turns_to_horizon':len(obs.legal_actions)*(budget-d['cost']['hidden_worlds'])*(15-obs.turn),
                          'scope':'最大研究経路の変化。適応判断への入力にはしない。'}
                        progress() # DB保存を含み得るので必ず計時の外。
        for r in a['rows']:
            f=next(x for x in a['rows'] if x['model']==r['model'] and x['repeat']==r['repeat'] and x['budget']==r['budget'] and x['method']=='Fixed')
            r['direct_measurement']['wall_difference']=r['direct_measurement']['wall_seconds']-f['direct_measurement']['wall_seconds']
            r['direct_measurement']['cpu_difference']=r['direct_measurement']['cpu_seconds']-f['direct_measurement']['cpu_seconds']
    finally:selection_observer.reset(token)
    direct={k:sum(d[k] for d in direct_costs) for k in KEYS}
    selection={k:research_selection[k]+direct[k] for k in KEYS};total={k:selection[k]+a['overhead_cost'][k] for k in KEYS}
    a.update(elapsed_seconds=perf_counter()-started,selection_cost=selection,total_cost=total,actual_research_compute_cost=total,
      reconstruction_cost=research_selection,direct_execution_cost=direct,measurement_environment=environment(c),
      scope='直接実測と再構成コストを区別。選択内容は照合済み。時間は環境ノイズを含み再現性対象外。')
    return stringify_stages(a)

def runtime_summary(positions):
    output=horizon_summary(positions)
    # 収集元別の集約も同じ独立配札単位で行う。
    for source in ('Random','Heuristic','ScoreAware','Zigzag','Reverse Zigzag'):
        selected=[p for p in positions if p['source']==source]
        for r in horizon_summary(selected):
            if r['stratum']=='all':output.append({**r,'stratum':'source:'+source})
    for r in output:
        grouped=defaultdict(lambda:defaultdict(list))
        for p in positions:
            label=r['stratum'];a=p['adaptive'];labels=('all',p['stratum']['class'],p['period'],f'legal:{a["legal_count"]}',f'remaining:{15-p["turn"]}','source:'+p['source'])
            if label not in labels:continue
            for row in a['rows']:
                if (row['model'],row['method'],row['budget'])!=(r['model'],r['method'],r['budget']):continue
                grouped[p['deal_hash']][p['position_hash']].append(row['direct_measurement'])
        for key in ('wall_seconds','cpu_seconds','wall_difference','cpu_difference','stop_check_count'):
            ds=[float(np.mean([np.mean([x[key] for x in entries]) for entries in ps.values()])) for ps in grouped.values()]
            r[key]=float(np.mean(ds)) if ds else None
        r['stop_check_seconds']=None;r['wall_difference_interval']=None
        r['time_uncertainty']='実時間は非有界かつ環境ノイズあり。小規模用の記述統計のみ。時間CI未実装。'
        r['analysis_role']='primary' if r['budget']==128 and r['method']!='Fixed' and r['stratum']=='all' else 'secondary'
    return output
