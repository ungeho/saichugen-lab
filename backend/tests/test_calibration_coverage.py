import json
from copy import deepcopy
from pathlib import Path
import pytest
from strategy_arena.experiments.calibration_coverage import inventory,fit_coverage,CoverageModel,Cell,validate_forecast
from strategy_arena.experiments.storage import ExperimentStore
from strategy_arena.experiments.storage_benchmark import run_storage_benchmark
from strategy_arena.experiments.budget_calibration import active_ledger,TimedStore
from strategy_arena.experiments.evolution import digest
from strategy_arena.experiments.noise_lab import study_estimate
from test_budget_calibration import config,model
from test_design_lab import setup
from test_middle_lab import wait
from strategy_arena.experiments.noise_lab import StudyJobs
from strategy_arena.experiments.evidence_lab import EvidenceLab

ENV={'os':'test','cpu':'test','python':'test'}

def job():
    stages=[]
    for stage in ('policy_reconstruction','reference','final'):
        for m in ('Random','Heuristic','ScoreAware'):
            stages.append(dict(stage=stage,model=m,period='middle',position_id='p',exclusive_wall_seconds=.1,exclusive_cpu_seconds=.1,completed=True,derived_games=32,simulated_turns=160))
    return dict(id='dev',status='Completed',created_at=None,config=dict(revision='phase40',stage='development_pilot',reference_worlds=16,final_worlds=16,deals=1),snapshot={'deal_hashes':['d'],'study_plan':{'environment':deepcopy(ENV)}},
      stage_measurements=stages,positions=[dict(position_hash='p',deal_hash='d',period='middle',turn=10,adaptive={'legal_count':7,'research_paths':[dict(model=m,budget=128) for m in ('Random','Heuristic','ScoreAware')]})])

def bench():
    return dict(id='bench',status='Completed',environment=ENV,cases=[dict(write_seconds=[.001,.002],history_rows=0,payload_bytes=100),dict(write_seconds=[.002],history_rows=250,payload_bytes=3000000)])

def fitted():return fit_coverage([job()],bench())

def test_inventory_quality_and_no_mutation():
    v=job();before=deepcopy(v);data=inventory([v]);assert v==before
    assert data['quality_counts']['使用可能']==9
    assert all(r['worlds'] is not None for r in data['records'])
    assert all(r['independent_deals']==1 for r in data['summaries'])

def test_profile_excluded_and_unknown_not_filled():
    v=job();v.pop('stage_measurements');v['positions']=[];v['runtime_measurements']=[dict(instrumented=True,wall_seconds=2,measurement_completed=True)]
    assert inventory([v])['quality_counts']['使用不可']==1
    v['runtime_measurements'][0]['instrumented']=False;v['snapshot']['study_plan']['environment']={}
    r=inventory([v])['records'][0];assert r['quality']=='情報不足' and r['worlds'] is None and r['environment']['cpu']=='Unknown'

def test_incomplete_intervals_excluded():
    v=job();v['stage_measurements'][0]['completed']=False
    assert inventory([v])['quality_counts']['使用不可']==1

def test_environment_and_measurement_not_pooled():
    a=job();b=job();b['id']='other';b['snapshot']['study_plan']['environment']['cpu']='other'
    assert len(inventory([a,b])['summaries'])==18
    with pytest.raises(ValueError):fit_coverage([a,b],bench())

def test_validation_cannot_fit_same_version():
    v=job();v['config']['stage']='independent_validation'
    assert inventory([v])['quality_counts']['条件付き使用可能']==9
    with pytest.raises(ValueError):fit_coverage([v],bench())

def test_model_roundtrip_hash_and_invalid_ranges():
    m=fitted();assert digest(m.model_dump(mode='json'))==digest(CoverageModel.model_validate_json(m.model_dump_json()).model_dump(mode='json'))
    for change in ({'rate':float('nan')},{'slow':.00001},{'max_legal':1}):
        with pytest.raises(ValueError):Cell(**{**next(iter(m.cells.values())).model_dump(),**change})

def test_forecast_pre_inputs_coverage_and_world_bounds():
    m=fitted();c=config(revision='phase40',calibration=m,turns=[10],storage_history_rows=50,expected_payload_bytes=500)
    f=study_estimate(c)['completion_forecast'];assert f['coverage_status']=='適用範囲内'
    assert f==study_estimate(c)['completion_forecast'] and f['conservative_seconds']>=f['predicted_seconds']
    g=study_estimate(config(revision='phase40',calibration=m,turns=[14],storage_history_rows=500,expected_payload_bytes=500))['completion_forecast']
    assert g['coverage_status']=='範囲外' and g['warnings']
    assert study_estimate(config(revision='phase40',calibration=m))['completion_forecast']['coverage_status']=='情報不足'

def test_new_model_not_accepted_on_old_revision():
    with pytest.raises(ValueError):config(calibration=fitted())
    with pytest.raises(ValueError):config(revision='phase40',calibration=model())
    with pytest.raises(ValueError):config(revision='phase40',calibration=fitted(),warmups=1)

def test_storage_callback_and_legacy_payload(tmp_path):
    store=ExperimentStore(tmp_path/'test.sqlite');p={'日本語':'内容'};i=store.save(p);metrics=[]
    assert store.update(i,p,on_write=metrics.append) is None
    assert store.get(i)==p and metrics==[{'written_bytes':len(json.dumps(p).encode()),'transactions':1}]
    with pytest.raises(KeyError):store.update('absent',p)

def test_timed_store_bytes_not_payload_mutation(tmp_path):
    store=ExperimentStore(tmp_path/'test.sqlite');i=store.save({'a':1});ledger={'rows':[],'stack':[]};token=active_ledger.set(ledger)
    try:TimedStore(store).update(i,{'a':2})
    finally:active_ledger.reset(token)
    assert store.get(i)=={'a':2} and ledger['rows'][0]['transactions']==1

def test_synthetic_storage_isolation(tmp_path):
    old=tmp_path/'old.sqlite';old.write_bytes(b'protected')
    result=run_storage_benchmark(tmp_path/'isolated',ENV)
    assert old.read_bytes()==b'protected' and result['status']=='Completed' and len(result['cases'])==18
    assert all(c['transactions']==c['save_count'] and c['rows_read']==c['history_rows']+1 for c in result['cases'])
    assert result['cases'][0]['payload_bytes']>16384
    with pytest.raises(ValueError):run_storage_benchmark(tmp_path,ENV,timeout_seconds=100)

def test_validation_unit_is_deal_and_partial_not_final():
    v=job();v['planned_positions']=deepcopy(v['positions']);v['snapshot']['study_plan']['completion_forecast']={'slots':[{'predicted_search_seconds':.5,'conservative_search_seconds':.8}]}
    r=validate_forecast(v);assert r['independent_deals']==1 and r['exceedances']==1 and r['exceedance_rate']==1
    v['status']='TimedOut';assert validate_forecast(v)['exceedance_rate'] is None
    v['planned_positions']*=2
    with pytest.raises(ValueError):validate_forecast(v)

def test_phase40_job_plan_storage_and_old_row_unchanged(tmp_path):
    design,ev,arena=setup(tmp_path);lab=StudyJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        old=design.store.save({'kind':'old','status':'TimedOut','seed':'18446744073709551615'})
        c=config(revision='phase40',calibration=fitted(),turns=[14],start_offset=40000)
        # Test environment must match the actual runtime environment.
        from strategy_arena.experiments.runtime_analysis import environment
        e=environment(c);c.calibration.environment={k:e[k] for k in ('os','cpu','python')}
        v=lab.register(c);frozen=deepcopy(v['snapshot']);lab.start(v['id'],v['condition_hash']);v=wait(lab,v['id'])
        assert v['status']=='Completed' and v['completion_audit']['primary_finalized']
        assert v['snapshot']==frozen and v['snapshot']['study_plan']['revision']=='phase40'
        assert v['forecast_coverage_validation']['independent_deals']==1
        assert lab.get(v['id'])['forecast_coverage_validation']==v['forecast_coverage_validation']
        assert design.store.get(old)=={'kind':'old','status':'TimedOut','seed':'18446744073709551615'}
        assert lab.calibration_inventory([v['id']])['records']
        with pytest.raises(ValueError):lab.calibration_inventory([])
    finally:lab.close();design.close();ev.close();arena.close()
