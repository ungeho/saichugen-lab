from copy import deepcopy
import json
import sqlite3
import time
import pytest
from fastapi.testclient import TestClient
from strategy_arena.api.app import create_app
from strategy_arena.experiments.storage import ExperimentStore
from strategy_arena.experiments.arena import arena_jobs
from strategy_arena.experiments.evolution import Evolution
from strategy_arena.strategies.declarative import DefinitionStore
from strategy_arena.experiments.evaluation_lab import EvaluationJobs,ablation_definitions
from strategy_arena.experiments.design_lab import DesignLab,PlanSpec,pilot_template,opponent_effect_difference,DesignPlanningInput,design_sample_plan,AllocationRequest,allocate


def setup(tmp_path):
    store=ExperimentStore(tmp_path/'design.sqlite');definitions=DefinitionStore(store.path)
    for d in ablation_definitions('adaptive_ablation'):definitions.add(d)
    arena=arena_jobs(store);evolution=Evolution(store,definitions,arena);evaluation=EvaluationJobs(store,definitions,arena,evolution)
    return DesignLab(store,definitions,evaluation,evolution),evaluation,arena


def spec(**kwargs):
    data=pilot_template().model_dump(mode='json');data['evaluation']['deals']=2;data.update(kwargs)
    return PlanSpec.model_validate(data)


def wait(lab,identifier,version=1):
    for _ in range(1000):
        view=lab.get(identifier,version)
        if view['state']!='Running':return view
        time.sleep(.01)
    raise AssertionError('Planが終了しません')


def test_draft_registration_hash_stable_version_and_reservations(tmp_path):
    lab,jobs,arena=setup(tmp_path)
    try:
        s=spec();draft=lab.draft(s);assert draft['state']=='Draft'
        assert lab.prepare(s)==lab.prepare(PlanSpec.model_validate_json(s.model_dump_json()))
        registered=lab.register(s.plan_id,1);assert registered['state']=='Registered' and len(registered['plan_hash'])==64
        assert len(registered['registered']['family'])==4
        with pytest.raises(ValueError):lab.draft(s)
        with pytest.raises(ValueError):lab.register(s.plan_id,1)
        changed=s.model_dump(mode='json');changed.update(version=2,parent_version=1);changed['evaluation']['start_offset']=900
        child=lab.draft(PlanSpec.model_validate(changed));assert child['state']=='Draft'
        lab.register(s.plan_id,2)
        assert lab.get(s.plan_id,1)['plan_hash']==registered['plan_hash']
        duplicate=spec(plan_id='duplicate-plan');lab.draft(duplicate)
        with pytest.raises(ValueError,match='予約'):lab.register(duplicate.plan_id,1)
        with pytest.raises(ValueError):lab.start(s.plan_id,1,'0'*64)
        assert lab.get(s.plan_id,1)['state']=='Registered'
    finally:lab.close();jobs.close();arena.close()


def test_shared_deals_opponent_effects_completion_and_data_integrity(tmp_path):
    lab,jobs,arena=setup(tmp_path)
    try:
        s=spec();lab.draft(s);r=lab.register(s.plan_id,1)
        assert r['registered']['plans'][0]['deal_seeds']==r['registered']['plans'][1]['deal_seeds']
        lab.start(s.plan_id,1,r['plan_hash']);done=wait(lab,s.plan_id)
        assert done['state']=='Completed' and done['usage']['completed_games']==48
        assert done['usage']['started_rollouts']==0
        cross=done['analysis']['between'][0]
        assert cross['evidence']['independent_deals']==2 and cross['verdict']=='hold'
        assert done['analysis']['planning'][0]['plan']['estimated_total'] is None
        assert DesignLab(lab.store,lab.definitions,jobs,lab.evolution).get(s.plan_id,1)['plan_hash']==r['plan_hash']
        evaluation_id=next(e['evaluation_id'] for e in done['events'] if e['state']=='Running')
        value=lab.store.get(evaluation_id);value['config']['policy_seed']=99;lab.store.update(evaluation_id,value)
        assert lab.get(s.plan_id,1)['state']=='Invalidated'
        assert lab.get(s.plan_id,1)['analysis'] is None
    finally:lab.close();jobs.close();arena.close()


def test_registered_hash_and_implementation_mismatch_block_execution(tmp_path,monkeypatch):
    import strategy_arena.experiments.design_lab as module
    lab,jobs,arena=setup(tmp_path)
    try:
        s=spec();lab.draft(s);r=lab.register(s.plan_id,1)
        original=module.runtime_info
        def changed():
            value=original();value['source_sha256']['game/engine.py']='changed';return value
        monkeypatch.setattr(module,'runtime_info',changed)
        with pytest.raises(ValueError,match='一致'):lab.start(s.plan_id,1,r['plan_hash'])
        assert lab.get(s.plan_id,1)['state']=='Invalidated' and not jobs.history()
    finally:lab.close();jobs.close();arena.close()


def test_sqlite_registration_tamper_detected(tmp_path):
    lab,jobs,arena=setup(tmp_path)
    try:
        s=spec();lab.draft(s);lab.register(s.plan_id,1)
        with sqlite3.connect(lab.store.path) as db:
            seq,payload=db.execute('SELECT seq,payload FROM design_events WHERE id=? ORDER BY seq DESC',(s.plan_id,)).fetchone()
            value=json.loads(payload);value['registered']['evaluation']['policy_seed']=123
            db.execute('UPDATE design_events SET payload=? WHERE seq=?',(json.dumps(value),seq))
        assert lab.get(s.plan_id,1)['state']=='Invalidated'
    finally:lab.close();jobs.close();arena.close()


def test_seed_partition_pilot_exclusion_and_budget_limits(tmp_path):
    lab,jobs,arena=setup(tmp_path)
    try:
        s=spec();data=s.model_dump(mode='json')
        with pytest.raises(ValueError):PlanSpec.model_validate({**data,'interpretation':'confirmatory'})
        with pytest.raises(ValueError):PlanSpec.model_validate({**data,'pilot_in_confirmatory':'included'})
        data['evaluation']['seed_partition']='final'
        with pytest.raises(ValueError):PlanSpec.model_validate(data)
        data=s.model_dump(mode='json');data['budget']['max_games']=10
        with pytest.raises(ValueError,match='予算'):lab.estimate(PlanSpec.model_validate(data))
        data=s.model_dump(mode='json');data['evaluation']['family_size']=1
        with pytest.raises(ValueError):PlanSpec.model_validate(data)
        data=s.model_dump(mode='json');data['evaluation']['deal_layout']='distinct'
        with pytest.raises(ValueError):PlanSpec.model_validate(data)
        data=s.model_dump(mode='json');data['interpretation']='confirmatory';data['evaluation']['seed_partition']='validation'
        confirm=PlanSpec.model_validate(data)
        assert lab.prepare(confirm)['plans'][0]['deal_seeds'][0]>=1000000
    finally:lab.close();jobs.close();arena.close()


def test_known_opponent_effect_difference_and_budget_planning():
    differences=opponent_effect_difference({'1':-1.,'2':2.},{'1':1.,'2':3.,'3':9.})
    assert differences=={'1':2.,'2':1.} and len(differences)==2
    result=design_sample_plan(DesignPlanningInput(observed_deals=20,sd_difference=1,minimum_effect=.5,seconds_per_deal=2,max_deals=100))
    assert result['estimated_total']==32
    assert result['normal_cost']['games']==32*2*2*6 and result['normal_cost']['seconds']==128
    assert not result['normal_cost']['within_game_budget']
    cross=design_sample_plan(DesignPlanningInput(observed_deals=20,sd_difference=1,minimum_effect=.5,contrast_bound=8))
    assert cross['conservative_total']>=4*result['conservative_total']-3
    assert design_sample_plan(DesignPlanningInput(observed_deals=2,sd_difference=1))['estimated_total'] is None


def test_allocation_is_deterministic_bounded_and_not_population_weights():
    request=AllocationRequest(items=[{'name':'unknown','priority':2,'seconds_per_deal':1},{'name':'known','untested':False,'observed_deals':20,'sd':1,'seconds_per_deal':2}],allowed_seconds=12,max_deals=10)
    result=allocate(request)
    assert result==allocate(request) and result['estimated_seconds']<=12
    assert sum(x['deals'] for x in result['allocation'])<=10
    assert sum(x['ratio'] for x in result['allocation'])==pytest.approx(1)
    assert result['allocation'][0]['deals']>=result['allocation'][1]['deals']
    assert '統合重みではない' in result['limitation']


def test_api_plan_export_cancel_and_no_auto_execution(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite')) as client:
        s=client.post('/api/design/template').json();s['evaluation']['deals']=10;s['budget'].update(max_independent_deals=10,max_games=240)
        r=client.post('/api/design/plans',json=s).json();assert r['state']=='Draft'
        assert client.get('/api/evaluation/studies').json()==[]
        url=f"/api/design/plans/{r['id']}/1"
        registered=client.post(url+'/register',json={}).json();assert registered['state']=='Registered'
        assert client.post(url+'/start',json={'plan_hash':'0'*64}).status_code==422
        running=client.post(url+'/start',json={'plan_hash':registered['plan_hash']}).json();assert running['state'] in ('Running','Completed')
        client.post(url+'/cancel',json={})
        for _ in range(500):
            value=client.get(url+'/export').json()
            if value['state']!='Running':break
            time.sleep(.01)
        assert value['state']=='Cancelled'
        assert value['usage']['completed_games']<240
        assert client.get('/api/design/plans').json()[0]['id']==r['id']


def test_time_budget_stops_without_completed_claim(tmp_path):
    lab,jobs,arena=setup(tmp_path)
    original=arena.runner
    def slow(config,on_row,check,on_partial):
        for _ in range(200):
            check();time.sleep(.01)
        original(config,on_row,check,on_partial)
    arena.runner=slow
    try:
        data=spec().model_dump(mode='json');data['budget'].update(allowed_seconds=1,measured_seconds_per_deal_composition=.001)
        s=PlanSpec.model_validate(data);lab.draft(s);r=lab.register(s.plan_id,1);lab.start(s.plan_id,1,r['plan_hash'])
        done=wait(lab,s.plan_id)
        assert done['state']=='Cancelled' and done['usage']['completed_games']==0
        assert any(e.get('stop_reason')=='time_budget' for e in done['events'])
    finally:lab.close();jobs.close();arena.close()

def test_plan_recommendation_creates_only_new_draft(tmp_path):
    lab,jobs,arena=setup(tmp_path)
    try:
        s=spec();lab.draft(s)
        view=lab.get(s.plan_id,1)
        assert view['recommendations'][0]['kind']=='family_not_registered'
        child=lab.recommendation_from_plan(s.plan_id,1,0)
        assert child['state']=='Draft' and child['version']==2
        assert child['spec']['parent_version']==1
        assert child['spec']['evaluation']['start_offset']!=s.evaluation.start_offset
        assert child['spec']['interpretation']=='exploratory'
        assert list(lab.store.iter_experiments())==[]
        assert lab.get(s.plan_id,1)['draft_hash']==view['draft_hash']
        with pytest.raises(ValueError):lab.recommendation_from_plan(s.plan_id,1,999)
    finally:lab.close();jobs.close();arena.close()
