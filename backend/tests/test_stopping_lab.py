import ast,inspect,json,subprocess,time
from copy import deepcopy
from dataclasses import asdict
import pytest
from fastapi.testclient import TestClient
from strategy_arena.api.app import create_app
from strategy_arena.experiments.adaptive_analysis import stopping,ranked,gap_statistics,analyze_adaptive,select
from strategy_arena.experiments.stopping_analysis import analyze_stopping,checkpoint,rule_fingerprint,select_validation_positions,stopping_summary,classify_stop,trace_sink
from strategy_arena.experiments.stopping_lab import StoppingConfig,StoppingJobs
from strategy_arena.experiments.evidence_lab import EvidenceLab
from test_design_lab import setup
from test_middle_lab import position,wait

def config(**kw):return StoppingConfig(**{'deals':1,'max_positions':1,'turns':[11],'models':['Random'],**kw})
def stable(v):
    if isinstance(v,list):return [stable(x) for x in v]
    if isinstance(v,dict):return {k:stable(x) for k,x in v.items() if not k.endswith('_seconds') and k!='stopping_sessions'}
    return v

def test_scientific_functions_identical_to_phase32():
    old=subprocess.check_output(['git','show','ff340423332b09baebe09aaf79734d017774d790:backend/src/strategy_arena/experiments/adaptive_analysis.py']).decode()
    tree=ast.parse(old)
    for fn in (stopping,ranked,gap_statistics):
        original=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==fn.__name__)
        assert ast.dump(original)==ast.dump(ast.parse(inspect.getsource(fn)).body[0])
    assert len(rule_fingerprint())==64

def test_logged_result_equals_unobserved_phase32_and_reproduces():
    o=position(14).observe(0);c=config();a=analyze_adaptive(o,c,'same');b=analyze_stopping(o,c,'same')
    assert stable(a)==stable(b)
    assert stable(b)==stable(analyze_stopping(o,c,'same'))
    assert len(b['stopping_sessions'])==6
    for s in b['stopping_sessions']:
        assert s['selected_card'] in [asdict(card) for card in o.legal_actions]
        assert s['selection_completed'] and s['checkpoints']
        t=s['checkpoints'][-1];assert t['final_selected_card']==s['selected_card']
        assert t['worlds']<=32 and not t['additional_sampling']
        assert 'minimum_conjunction_margin' in t['components']

def test_components_slack_and_budget_classifications():
    c=config();m={'method':'Gap-Adaptive','budget':32,'effective_cap':32}
    t={'worlds':16,'gap':.5,'paired_se':.2,'contrasts':[{'card':{'rank':1,'suit':0},'gap':.5,'se':.2}],
       'stop_reason':None,'candidates':[]}
    v=checkpoint(t,m,c);assert v['components']['gap_margin']==0 and not v['components']['gap_condition']
    assert v['components']['minimum_conjunction_margin']==pytest.approx(.05)
    assert v['additional_sampling'] and t=={**t}
    row={'early_stop':False,'effective_cap':32,'budget':32,'method':'Fixed'}
    assert classify_stop(row)=='completed_fixed_budget'
    assert classify_stop({**row,'method':'Gap-Adaptive'})=='max_worlds'
    assert classify_stop({**row,'effective_cap':16})=='max_derived_games'
    assert classify_stop({**row,'early_stop':True})=='early_stop'

@pytest.mark.parametrize('kw',[{'partition':'development'},{'start_offset':1},{'start_offset':2000000},
 {'gap_threshold':.4},{'uncertainty_z':3},{'initial_worlds':32},{'batch_worlds':8},{'minimum_gap':0},
 {'diagnostic_source_id':'old'},{'historical_limit':1},{'cross_models':True},{'collectors':['Random']}])
def test_frozen_configuration_rejects_changes(kw):
    with pytest.raises(ValueError):config(**kw)

def test_selection_is_deterministic_and_not_based_on_outcomes():
    rows=[]
    for i,p in enumerate(('early','middle','before_final_round','final_round')):
        for d in range(2):rows.append({'position_hash':f'{i}-{d}','deal_hash':str(d),'period':p,'source':'Random','stratum':{'class':['tie','highest','strict_middle','lowest'][i]}})
    a=select_validation_positions(rows,4);assert a==select_validation_positions(list(reversed(rows)),4)
    assert len({r['period'] for r in a})==4 and len({r['deal_hash'] for r in a})==2

def test_cluster_denominators_and_stop_uncertainty():
    o=position(14).observe(0);a=analyze_stopping(o,config(),'summary')
    p={'position_hash':'one','deal_hash':'deal','turn':14,'period':'final_round','stratum':{'class':'tie','strict_middle':False},'adaptive':a}
    summaries=stopping_summary([p,{**p,'position_hash':'two'}])
    assert all(s['independent_deals']==1 for s in summaries)
    assert all(s['early_stop_interval']==[0.,1.] for s in summaries)
    for s in summaries:
        assert s['reward_difference_evidence']['interval'] is None
        if s['stratum']=='all':assert s['positions']==2 and s['analysis_role']=='primary'

def test_hash_saved_plan_coverage_old_rows_and_reload(tmp_path):
    design,ev,arena=setup(tmp_path);lab=StoppingJobs(design.store,design,EvidenceLab(design.store,design));old=design.store.save({'old':'keep'})
    try:
        v=lab.register(config(start_offset=1940000));assert v['snapshot']['stopping_plan']['rules_hash']==rule_fingerprint()
        with pytest.raises(ValueError):lab.start(v['id'],'bad')
        lab.start(v['id'],v['condition_hash']);v=wait(lab,v['id']);assert v['status']=='Completed',v.get('error')
        assert len(v['planned_positions'])==len(v['positions']) and not v['missing_positions']
        assert v['stopping_trace'] and len(v['coverage'])==20
        assert any(r['status']=='not_evaluated' for r in v['coverage'])
        assert design.store.get(old)=={'old':'keep'}
        new=StoppingJobs(design.store,design,EvidenceLab(design.store,design));assert new.get(v['id'])['stopping_trace']==v['stopping_trace'];new.close()
        assert json.loads(json.dumps(v))['condition_hash']==v['condition_hash']
        with pytest.raises(ValueError):lab.register(config(start_offset=1940000))
    finally:lab.close();design.close();ev.close();arena.close()

def test_running_cancel_retains_last_checkpoint(tmp_path,monkeypatch):
    import strategy_arena.experiments.adaptive_analysis as mod
    real=mod.draw
    def slow(*a,**kw):time.sleep(.02);return real(*a,**kw)
    monkeypatch.setattr(mod,'draw',slow)
    design,ev,arena=setup(tmp_path);lab=StoppingJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        v=lab.register(config(start_offset=1950000));lab.start(v['id'],v['condition_hash'])
        for _ in range(300):
            j=lab.get(v['id'])
            if any(s['checkpoints'] for s in j.get('stopping_trace',[])):break
            time.sleep(.01)
        assert any(s['checkpoints'] for s in j['stopping_trace'])
        lab.cancel(v['id']);j=wait(lab,v['id']);assert j['status']=='Cancelled'
        assert any(s['classification']=='cancelled' for s in j['stopping_trace']) and j['cluster_summary'] is None
    finally:lab.close();design.close();ev.close();arena.close()

def test_api_namespace_missing_ids_and_cancel(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite')) as client:
        r=client.post('/api/stopping/jobs',json=config(start_offset=1960000).model_dump(mode='json'));assert r.status_code==201,r.text
        v=r.json();assert client.get('/api/stopping/jobs/'+v['id']+'/export').json()['status']=='Registered'
        assert client.get('/api/adaptive/jobs/'+v['id']).status_code==404
        assert client.get('/api/stopping/jobs/missing').status_code==404
        assert client.post('/api/stopping/jobs/'+v['id']+'/cancel',json={}).json()['status']=='Cancelled'
