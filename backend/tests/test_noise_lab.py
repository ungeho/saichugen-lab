import ast,inspect,json,subprocess,sys,time
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from strategy_arena.api.app import create_app
from strategy_arena.experiments.noise_lab import StudyConfig,StudyJobs,study_estimate
from strategy_arena.experiments.noise_analysis import analyze_noise,analyze_divergence,study_summary,stats,stopping_meter,noise_order
from strategy_arena.experiments.adaptive_analysis import select,stopping
from strategy_arena.experiments.stopping_analysis import rule_fingerprint
from strategy_arena.experiments.evidence_lab import EvidenceLab
from test_design_lab import setup
from test_middle_lab import position,wait

def config(**kw):return StudyConfig(**{'turns':[14],'max_positions':1,'deals':1,**kw})

def test_baseline_select_identical_and_meter_restored_without_behavior_change():
    old=subprocess.check_output(['git','show','007e6c816882920d7a23fcc94c09d2619fe3d9f3:backend/src/strategy_arena/experiments/adaptive_analysis.py']).decode()
    assert ast.dump(next(n for n in ast.parse(old).body if isinstance(n,ast.FunctionDef) and n.name=='select'))==ast.dump(ast.parse(inspect.getsource(select)).body[0])
    o=position(14).observe(0);c=config();a=select(o,o.legal_actions,'Random',42,32,'Gap-Adaptive',c);before=sys.getprofile()
    with stopping_meter(True) as meter:b=select(o,o.legal_actions,'Random',42,32,'Gap-Adaptive',c)
    assert sys.getprofile() is before and meter['calls']==len(b['trace']) and meter['seconds']>=0
    for k in ('selected_card','candidates','stop_reason'):assert a[k]==b[k]
    with pytest.raises(RuntimeError):
        with stopping_meter(True):raise RuntimeError('failure')
    assert sys.getprofile() is before


def test_distribution_and_zero_cv():
    s=stats([1,2,3,4]);assert s['median']==2.5 and s['mean']==2.5 and s['iqr']==1.5
    assert s['sd']==pytest.approx(1.2909944487) and s['cv']==pytest.approx(s['sd']/2.5)
    assert stats([])['mean'] is None and stats([0,0])['cv'] is None and stats([1])['sd'] is None


def test_r_fixed_seed_warmups_modes_and_costs():
    g=position(14);before=deepcopy(g.__dict__);c=config(measure_stopping=True);a=analyze_noise(g.observe(0),c,'noise')
    assert g.__dict__==before
    records=a['noise_records'];assert len(records)==24 and len({r['seed'] for r in records})==1
    assert sum(r['phase']=='warmup' for r in records)==6
    assert all(r['path_matches'] and isinstance(r['seed'],str) for r in records)
    for r in records:
        if r['instrumented']:assert r['profiled_calls']==r['stop_check_count'] and r['stop_check_seconds'] is not None
        else:assert r['stop_check_seconds'] is None
    costs=[a[k]['derived_games'] for k in ('reconstruction_cost','warmup_cost','measurement_cost')]
    assert sum(costs)==a['total_cost']['derived_games'] and costs[1]>0
    p={'deal_hash':'d','position_hash':'p','adaptive':a};summary=study_summary([p]);assert len(summary)==6
    assert all(s['wall']['n']==3 and s['independent_deals']==1 for s in summary)
    assert len({tuple(str(x) for x in noise_order(c,'p','Random',i,32,'measurement')) for i in range(5)})>1


def test_d_seed_reproducibility_shared_final_denominators_and_negative_regret():
    o=position(14).observe(0);c=config(series='D',warmups=0);a=analyze_divergence(o,c,'d');b=analyze_divergence(o,c,'d')
    assert [r['selected_card'] for r in a['rows']]==[r['selected_card'] for r in b['rows']]
    assert len(set(a['stage_seeds'].values()))==3 and all(isinstance(x,str) for x in a['stage_seeds'].values())
    p={'position_hash':'one','deal_hash':'d','turn':14,'period':'final_round','stratum':{'class':'tie'},'adaptive':a}
    summaries=study_summary([p,{**p,'position_hash':'two'}]);assert all(r['independent_deals']==1 for r in summaries)
    assert all(r['positions']==2 for r in summaries if r['stratum']=='all')
    for r in a['rows']:
        d=r['decision_divergence'];assert d['diverged']==(r['selected_card']!=r['fixed_horizon_card'])
        assert d['independent_reward_difference']==r['evaluations'][0]['minus_fixed']['mean']
        assert isinstance(d['selection_seed'],str)
    # 分岐しない局面を分母から落とさない。
    altered=deepcopy(p)
    for r in altered['adaptive']['rows']:
        r['evaluations'][0]['matches_fixed']=r['method']=='Fixed'
    s=next(r for r in study_summary([p,{**altered,'position_hash':'three'}]) if r['stratum']=='all' and r['method']=='Gap-Adaptive')
    assert s['positions']==2 and s['divergence_rate']==.5

@pytest.mark.parametrize('kw',[{'series':'R','stage':'independent_validation','partition':'validation','start_offset':1930000},
 {'series':'D','warmups':1},{'series':'D','warmups':0,'measure_stopping':True},{'measurement_repeats':1},
 {'warmups':3},{'gap_threshold':.4},{'uncertainty_z':3},{'minimum_gap':0},{'batch_worlds':8},
 {'series':'D','warmups':0,'stage':'independent_validation','partition':'validation','start_offset':1920000,'budgets':[128]},
 {'series':'D','warmups':0,'stage':'independent_validation','partition':'validation','start_offset':1930000,'budgets':[32]},
 {'turns':[0],'max_positions':8,'deals':4,'measurement_repeats':10,'measure_stopping':True,'budgets':[256]}])
def test_configuration_safety(kw):
    with pytest.raises(ValueError):config(**kw)

@pytest.mark.parametrize('series',['R','D'])
def test_plan_storage_old_rows_and_api_precision(tmp_path,series):
    design,ev,arena=setup(tmp_path);lab=StudyJobs(design.store,design,EvidenceLab(design.store,design));old=design.store.save({'old':'keep'})
    try:
        c=config(series=series,warmups=0,start_offset=36200 if series=='R' else 36300);v=lab.register(c)
        assert 'warmup' in v['snapshot']['study_plan']['environment']['prior_computation']
        assert v['snapshot']['study_plan']['series']==series and v['snapshot']['study_plan']['rules_hash']==rule_fingerprint()
        lab.start(v['id'],v['condition_hash']);v=wait(lab,v['id']);assert v['status']=='Completed',v.get('error')
        assert v['cluster_summary'] and v['evaluated_independent_deals']==1 and not v['missing_positions']
        assert design.store.get(old)=={'old':'keep'} and json.loads(json.dumps(v))['positions']==v['positions']
        assert all(isinstance(r['seed'],str) for r in v['runtime_measurements']+v['stopping_trace'])
        other=StudyJobs(design.store,design,EvidenceLab(design.store,design));assert other.get(v['id'])['positions']==v['positions'];other.close()
    finally:lab.close();design.close();ev.close();arena.close()
    with TestClient(create_app(tmp_path/'api.sqlite')) as client:
        r=client.post('/api/runtime-divergence/jobs',json=c.model_dump(mode='json'));assert r.status_code==201,r.text
        v=r.json();assert client.get('/api/runtime-divergence/jobs/'+v['id']+'/export').json()['series']==series
        assert client.get('/api/stopping-runtime/jobs/'+v['id']).status_code==404
        assert client.get('/api/runtime-divergence/jobs/missing').status_code==404
        assert client.post('/api/runtime-divergence/jobs/'+v['id']+'/cancel',json={}).json()['status']=='Cancelled'


def test_cancel_measurement_partial_not_zero(tmp_path,monkeypatch):
    import strategy_arena.experiments.noise_analysis as mod
    from threading import Event
    gate=Event();entered=Event();real=mod.select;calls=[0]
    def pause(*a,**kw):
        calls[0]+=1
        if calls[0]==2:entered.set();gate.wait(5)
        return real(*a,**kw)
    monkeypatch.setattr(mod,'select',pause)
    design,ev,arena=setup(tmp_path);lab=StudyJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        v=lab.register(config(start_offset=36400));lab.start(v['id'],v['condition_hash']);assert entered.wait(5)
        lab.cancel(v['id']);gate.set();v=wait(lab,v['id']);assert v['status']=='Cancelled' and v['cluster_summary'] is None
        assert v['runtime_measurements'][0]['wall_seconds'] is None and not v['runtime_measurements'][0]['measurement_completed']
    finally:gate.set();lab.close();design.close();ev.close();arena.close()
