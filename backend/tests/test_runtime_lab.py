import ast,inspect,json,subprocess,time
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from strategy_arena.api.app import create_app
from strategy_arena.experiments.runtime_lab import RuntimeConfig,RuntimeJobs,runtime_estimate
from strategy_arena.experiments.runtime_analysis import analyze_runtime,execution_order,environment,runtime_summary,seed_strings,runtime_sink
from strategy_arena.experiments.adaptive_analysis import stopping,ranked,gap_statistics,select,selection_observer
from strategy_arena.experiments.horizon_analysis import reconstruct
from strategy_arena.experiments.stopping_analysis import rule_fingerprint
from strategy_arena.experiments.evidence_lab import EvidenceLab
from test_design_lab import setup
from test_middle_lab import position,wait

def config(**kw):return RuntimeConfig(**{'deals':1,'max_positions':1,'turns':[14],'models':['Random'],'budgets':[32],**kw})

def decisions(a):return [(r['method'],r['budget'],r['seed'],r['selected_card'],r['cost']['hidden_worlds'],r['evaluations']) for r in a['rows']]

def test_phase34_semantics_unmodified_and_trace_has_no_effect():
    old=subprocess.check_output(['git','show','7db4b3395ba0efc5745099f871cce8c9dbeecf74:backend/src/strategy_arena/experiments/adaptive_analysis.py']).decode()
    tree=ast.parse(old)
    for f in (stopping,ranked,gap_statistics,select):
        original=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==f.__name__)
        assert ast.dump(original)==ast.dump(ast.parse(inspect.getsource(f)).body[0])
    c=config();o=position(14).observe(0);a=select(o,o.legal_actions,'Random',42,32,'Fixed',c)
    t=selection_observer.set(lambda *args:None)
    try:b=select(o,o.legal_actions,'Random',42,32,'Fixed',c)
    finally:selection_observer.reset(t)
    assert a['selected_card']==b['selected_card'] and a['candidates']==b['candidates']
    assert rule_fingerprint()=='b774337d8b3525d0f254d7dc9611e43403fc8db77d2001b2ff962806e4126fe4'

@pytest.mark.parametrize('budget',[32,64,128,256])
def test_direct_matches_reconstruction_and_seed_reproduces(budget):
    g=position(14);before=deepcopy(g.__dict__);o=g.observe(0);c=config(budgets=[budget]);a=analyze_runtime(o,c,'same')
    assert g.__dict__==before and decisions(a)==decisions(analyze_runtime(o,c,'same'))
    assert len(set(a['stage_seeds'].values()))==3 and all(isinstance(s,str) for s in a['stage_seeds'].values())
    for r in a['rows']:
        d=r['direct_measurement'];assert d['path_matches'] and d['measurement_completed']
        assert d['cost']['derived_games']==r['cost']['derived_games'] and d['wall_seconds']>=0 and d['cpu_seconds']>=0
        assert d['stop_check_count']==len(r['trace']) and d['stop_check_seconds'] is None
        assert isinstance(r['seed'],str)
    assert a['actual_research_compute_cost']['derived_games']==a['reconstruction_cost']['derived_games']+a['direct_execution_cost']['derived_games']+a['overhead_cost']['derived_games']


def test_order_environment_and_large_seeds():
    c=config();orders=[execution_order(c,'p','Random',r,128) for r in range(6)]
    assert orders==[execution_order(c,'p','Random',r,128) for r in range(6)] and len({tuple(o) for o in orders})>1
    e=environment(c);assert not e['parallel'] and not e['warmup'] and e['processes']==1
    assert all(e[k] for k in ('python','os','wall_timer','cpu_timer'))
    x=seed_strings({'seed':2**64-1,'stage_seeds':{'policy':2**63+3},'score':3});assert x['seed']==str(2**64-1) and x['score']==3
    assert x['stage_seeds']['policy']==str(2**63+3)


def test_progress_persistence_excluded_from_direct_measurement(monkeypatch):
    import strategy_arena.experiments.runtime_analysis as mod
    calls=[];clock=[0.]
    def timer():clock[0]+=.1;return clock[0]
    monkeypatch.setattr(mod,'perf_counter',timer);monkeypatch.setattr(mod,'process_time',timer)
    def progress():clock[0]+=1000;calls.append(True)
    a=analyze_runtime(position(14).observe(0),config(),'timing',progress=progress)
    assert calls
    assert all(r['direct_measurement']['wall_seconds']<1 for r in a['rows'])

@pytest.mark.parametrize('kw',[{'stage':'independent_validation'},{'partition':'validation'},
 {'stage':'independent_validation','partition':'validation','start_offset':1920000,'budgets':[32]},
 {'stage':'independent_validation','partition':'validation','start_offset':1910000,'budgets':[128]},
 {'start_offset':999999,'deals':2,'max_positions':2},{'start_offset':2000000},
 {'gap_threshold':.4},{'batch_worlds':8},{'uncertainty_z':3},{'minimum_gap':0},{'budgets':[16]},
 {'turns':[0],'max_positions':8,'deals':4,'models':['Random','Heuristic','ScoreAware'],'budgets':[256]}])
def test_invalid_partition_rules_and_limits(kw):
    with pytest.raises(ValueError):config(**kw)


def test_period_cost_bounds_and_cluster_unit():
    c=RuntimeConfig();assert runtime_estimate(c)['derived_games_upper']==8928
    a=analyze_runtime(position(14).observe(0),config(),'summary')
    p={'position_hash':'p','deal_hash':'d','turn':14,'period':'final_round','source':'Random','stratum':{'class':'tie'},'adaptive':a}
    s=runtime_summary([p,{**p,'position_hash':'p2'}]);assert all(x['independent_deals']==1 for x in s)
    assert any(x['stratum']=='source:Random' for x in s)
    assert all(x['wall_difference_interval'] is None and x['reward_difference_evidence']['interval'] is None for x in s)


def test_plan_storage_old_rows_seed_strings_and_reload(tmp_path):
    design,ev,arena=setup(tmp_path);lab=RuntimeJobs(design.store,design,EvidenceLab(design.store,design));old=design.store.save({'old':'keep'})
    try:
        v=lab.register(config(start_offset=34300));assert v['snapshot']['runtime_plan']['primary_budget']==128
        with pytest.raises(ValueError):lab.start(v['id'],'bad')
        lab.start(v['id'],v['condition_hash']);v=wait(lab,v['id']);assert v['status']=='Completed',v.get('error')
        assert v['runtime_measurements'] and not v['missing_positions'] and v['cluster_summary']
        assert any(r['status']=='not_evaluated' for r in v['runtime_coverage'])
        assert all(isinstance(r['seed'],str) for r in v['runtime_measurements']+v['stopping_trace'])
        assert all(isinstance(s,str) for p in v['positions'] for s in p['adaptive']['stage_seeds'].values())
        raw=design.store.get(v['id']);assert raw['runtime_measurements']==v['runtime_measurements'] and raw['stopping_trace']==v['stopping_trace']
        assert json.loads(json.dumps(v))['positions']==v['positions'] and design.store.get(old)=={'old':'keep'}
        other=RuntimeJobs(design.store,design,EvidenceLab(design.store,design));assert other.get(v['id'])['positions']==v['positions'];other.close()
    finally:lab.close();design.close();ev.close();arena.close()


def test_api_namespace_validation_and_cancel(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite')) as client:
        r=client.post('/api/stopping-runtime/jobs',json=config(start_offset=34400).model_dump(mode='json'));assert r.status_code==201,r.text
        v=r.json();assert client.get('/api/stopping-runtime/jobs/'+v['id']+'/export').json()['status']=='Registered'
        assert client.get('/api/stopping-horizon/jobs/'+v['id']).status_code==404
        assert client.get('/api/stopping-runtime/jobs/missing').status_code==404
        assert client.post('/api/stopping-runtime/jobs/'+v['id']+'/cancel',json={}).json()['status']=='Cancelled'


def test_direct_cancel_partial_measurement_not_completed(tmp_path,monkeypatch):
    import strategy_arena.experiments.runtime_analysis as mod
    real=mod.select
    def slow(*a,**kw):
        time.sleep(.05);return real(*a,**kw)
    monkeypatch.setattr(mod,'select',slow)
    design,ev,arena=setup(tmp_path);lab=RuntimeJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        v=lab.register(config(start_offset=34500,budgets=[128]));lab.start(v['id'],v['condition_hash'])
        for _ in range(300):
            v=lab.get(v['id'])
            if any(not r['measurement_completed'] for r in v.get('runtime_measurements',[])):break
            time.sleep(.01)
        assert v['runtime_measurements'];lab.cancel(v['id']);v=wait(lab,v['id'])
        assert v['status']=='Cancelled' and v['cluster_summary'] is None
        assert any(not r['measurement_completed'] and r['wall_seconds'] is None for r in v['runtime_measurements'])
    finally:lab.close();design.close();ev.close();arena.close()
