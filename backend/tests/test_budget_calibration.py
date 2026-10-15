import json,random,subprocess,ast,inspect,time
from copy import deepcopy
import pytest
from strategy_arena.experiments.budget_calibration import active_ledger,stage_span,breakdown,CalibrationModel,forecast,deal_progress,completion_audit,fit_calibration
from strategy_arena.experiments.noise_lab import StudyJobs,StudyConfig,study_estimate
from strategy_arena.experiments.multideal_analysis import analyze_multideal
from strategy_arena.experiments.adaptive_analysis import select,stopping
from strategy_arena.experiments.evidence_lab import EvidenceLab
from test_design_lab import setup
from test_middle_lab import position,wait

def model():
    rates={s+':'+m:.0001 for s in ('policy','reference','final') for m in ('Random','Heuristic','ScoreAware')}
    return CalibrationModel(source_ids=['calibration-only'],rates=rates,slow_rates={k:v*2 for k,v in rates.items()},management_seconds=0,conservative_management_seconds=10,note='人工単価のテスト用モデル')

def config(**kw):return StudyConfig(**{'revision':'phase39','series':'D','start_offset':39000,'deals':1,'max_positions':1,'turns':[14],
  'budgets':[128],'models':['Random','Heuristic','ScoreAware'],'repeats':1,'warmups':0,'calibration':model(),**kw})

def test_frozen_select_stopping():
    old=subprocess.check_output(['git','show','dfccdcb:backend/src/strategy_arena/experiments/adaptive_analysis.py']).decode()
    for f in (select,stopping):assert ast.dump(next(x for x in ast.parse(old).body if isinstance(x,ast.FunctionDef) and x.name==f.__name__))==ast.dump(ast.parse(inspect.getsource(f)).body[0])

def test_nested_exclusive_and_unmeasured_residual_and_duplicate_detection():
    ledger={'rows':[],'stack':[]};token=active_ledger.set(ledger)
    try:
        with stage_span('parent'):
            with stage_span('child'):sum(range(500))
    finally:active_ledger.reset(token)
    total=ledger['rows'][0]['wall_seconds']+.1;b=breakdown(ledger['rows'],total)
    assert b['unmeasured_residual_seconds']==pytest.approx(.1) and not b['overlap_or_timer_error']
    assert all(r['exclusive_wall_seconds']>=0 and r['exclusive_cpu_seconds']>=0 for r in ledger['rows'])
    assert breakdown(ledger['rows']+[ledger['rows'][1]],total)['overlap_or_timer_error']
    assert breakdown(ledger['rows'],0)['unmeasured_residual_seconds']<0

def test_interrupted_interval_kept():
    ledger={'rows':[],'stack':[]};token=active_ledger.set(ledger)
    try:
        with pytest.raises(InterruptedError):
            with stage_span('partial'):raise InterruptedError('TimedOut')
    finally:active_ledger.reset(token)
    assert ledger['rows'][0]['wall_seconds']>=0 and not ledger['rows'][0]['completed'] and not ledger['stack']

def test_measuring_does_not_change_cards_samples_cost_or_rng():
    c=config();obs=position(14).observe(0);state=random.getstate();a=analyze_multideal(obs,c,'same',0)
    ledger={'rows':[],'stack':[]};token=active_ledger.set(ledger)
    try:b=analyze_multideal(obs,c,'same',0)
    finally:active_ledger.reset(token)
    assert random.getstate()==state and a['stage_seeds']==b['stage_seeds']
    for x,y in zip(a['rows'],b['rows']):
        for k in ('selected_card','candidates','evaluations','trace','stop_reason'):assert x[k]==y[k]
        for k in ('derived_games','simulated_turns','hidden_worlds'):assert x['cost'][k]==y['cost'][k]
    assert {r['stage'] for r in ledger['rows']}=={'policy_reconstruction','policy_direct','reference','final'}

def test_deterministic_forecast_and_invalid_calibration():
    c=config();a=study_estimate(c);assert a==study_estimate(c)
    f=a['completion_forecast'];assert f['conservative_seconds']>=f['predicted_seconds'] and not f['guarantee']
    assert study_estimate(config(calibration=None))['completion_forecast']['rating']=='データ不足で判断困難'
    with pytest.raises(ValueError):config(stage='independent_validation',partition='validation',start_offset=1960000,calibration=None)
    with pytest.raises(ValueError):CalibrationModel(**{**model().model_dump(),'rates':{'policy:Random':float('nan')}})

def test_progress_partial_vs_not_started():
    v={'status':'TimedOut','planned_positions':[{'position_hash':str(i),'deal_hash':str(i)} for i in range(3)],'positions':[{'position_hash':'0'}],
      'runtime_measurements':[{'position_hash':'1','measurement_completed':False}],'stopping_trace':[]}
    assert deal_progress(v)['counts']=={'complete':1,'partial':1,'not_started':1}

def test_progress_before_collection_and_multiple_positions_one_deal():
    v={'status':'Registered','snapshot':{'deal_hashes':['a','b']},'planned_positions':[],'positions':[]}
    assert deal_progress(v)['counts']=={'complete':0,'partial':0,'not_started':2}
    v.update(status='Running',planned_positions=[{'position_hash':'p','deal_hash':'a'},{'position_hash':'q','deal_hash':'a'}],positions=[{'position_hash':'p'}])
    assert deal_progress(v)['counts']=={'complete':0,'partial':1,'not_started':1}

def test_new_plan_saved_old_timedout_unchanged_and_completion_gated(tmp_path):
    design,ev,arena=setup(tmp_path);lab=StudyJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        v=lab.register(config());snap=deepcopy(v['snapshot']);assert 'completion_forecast' in snap['study_plan']
        lab.start(v['id'],v['condition_hash']);v=wait(lab,v['id']);assert v['status']=='Completed',v.get('error')
        assert v['completion_audit']['primary_finalized'] and v['cluster_summary'] and v['snapshot']==snap
        assert v['completion_progress']['counts']=={'complete':1,'partial':0,'not_started':0}
        assert v['cost_breakdown']['unmeasured_residual_seconds']>=0 and not v['cost_breakdown']['overlap_or_timer_error']
        assert json.loads(json.dumps(v))['stage_measurements']==v['stage_measurements']
        raw=design.store.get(v['id']);raw['status']='TimedOut';raw['result_hash']=None;design.store.update(v['id'],raw);before=design.store.get(v['id'])
        got=lab.get(v['id']);assert not got['completion_audit']['primary_finalized'] and got['cluster_summary'] is None
        assert design.store.get(v['id'])==before
        with pytest.raises(ValueError):fit_calibration([{**v,'config':{**v['config'],'stage':'independent_validation'}}])
    finally:lab.close();design.close();ev.close();arena.close()

def test_calibration_deals_not_reused(tmp_path):
    from strategy_arena.experiments.evidence_lab import deal_identity
    from strategy_arena.experiments.rollout_quality import runtime_info
    design,ev,arena=setup(tmp_path);lab=StudyJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        m=model().model_copy(update={'source_deal_hashes':[deal_identity(39000,runtime_info()['source_sha256'])]})
        with pytest.raises(ValueError):lab.register(config(calibration=m))
    finally:lab.close();design.close();ev.close();arena.close()

@pytest.mark.parametrize('ids',[None,[],['same','same'],[{}],[1],[None],[''],'invalid-list'])
def test_invalid_calibration_ids_are_client_errors(tmp_path,ids):
    from fastapi.testclient import TestClient
    from strategy_arena.api.app import create_app
    with TestClient(create_app(str(tmp_path/'api.sqlite')),raise_server_exceptions=False) as client:
        assert client.post('/api/runtime-divergence/calibration',json={'source_ids':ids}).status_code==422
