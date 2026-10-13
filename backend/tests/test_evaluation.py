from copy import deepcopy
from math import log,sqrt
import json
import time
import numpy as np
import pytest
from fastapi.testclient import TestClient
from strategy_arena.api.app import create_app
from strategy_arena.experiments.evaluation_statistics import PlanningInput,plan_samples,fixed_evidence,factorial_contrasts
from strategy_arena.experiments.evaluation_lab import EvaluationRequest,EvaluationJobs,ablation_definitions,estimate_evaluation,analyze_arena
from strategy_arena.experiments.arena import arena_jobs
from strategy_arena.experiments.storage import ExperimentStore
from strategy_arena.experiments.evolution import Evolution
from strategy_arena.strategies.declarative import DefinitionStore


def test_known_sample_size_uses_design_effect_not_observed_mean():
    # ceil((1.959964+.841621)^2/.5^2)=32
    r=PlanningInput(observed_deals=20,mean_difference=.1,sd_difference=1.,minimum_effect=.5,seconds_per_deal=2.)
    p=plan_samples(r);assert p['estimated_total']==32 and p['estimated_additional']==12 and p['estimated_seconds']==24
    assert plan_samples(r.model_copy(update={'mean_difference':3.}))['estimated_total']==32
    assert plan_samples(r.model_copy(update={'alpha':.01}))['estimated_total']>32
    assert plan_samples(r.model_copy(update={'power':.9}))['estimated_total']>32
    assert plan_samples(r.model_copy(update={'comparisons':4}))['estimated_total']>32
    assert not plan_samples(r.model_copy(update={'max_deals':10}))['feasible']
    assert p['conservative_total']>p['estimated_total']


@pytest.mark.parametrize('n,sd',[(2,1.),(0,None),(20,0.)])
def test_pilot_required_no_precise_estimate(n,sd):
    p=plan_samples(PlanningInput(observed_deals=n,sd_difference=sd))
    assert p['status']=='pilot_required' and p['estimated_total'] is None and p['estimated_additional'] is None


def test_fixed_intervals_bonferroni_and_no_optional_stopping():
    values=[1.]*100
    r=fixed_evidence(values,completed=True,confirmatory=True)
    radius=8*sqrt(log(40)/200)
    assert r['interval']==pytest.approx([1-radius,1+radius])
    assert r['interval'][0]<1<r['interval'][1] # 分散0でも0幅にしない
    assert fixed_evidence(values,comparisons=8,completed=True,confirmatory=True)['interval'][0]<r['interval'][0]
    assert fixed_evidence(values,completed=False,confirmatory=True)['interval'] is None
    assert fixed_evidence([4.]*2000,completed=True,confirmatory=False)['decision']=='hold'
    assert fixed_evidence([4.]*2000,completed=True,confirmatory=True)['decision']=='positive'
    assert fixed_evidence([4.]*2,completed=True,confirmatory=True)['interval'] is None


def test_factorial_hand_calculation():
    result=factorial_contrasts([[1,0],[2,2],[3,1],[5,4]])
    assert result=={'factor_a':[1,2],'factor_b':[2,1],'combined':[4,4],'interaction':[1,1]}
    with pytest.raises(ValueError):factorial_contrasts([[0],[1],[2]])


def setup(tmp_path):
    store=ExperimentStore(tmp_path/'lab.sqlite');definitions=DefinitionStore(store.path);arena=arena_jobs(store)
    return EvaluationJobs(store,definitions,arena,Evolution(store,definitions,arena)),definitions,arena


def wait(jobs,identifier):
    for _ in range(500):
        r=jobs.get(identifier)
        if r['status']!='running':return r
        time.sleep(.01)
    raise AssertionError('実験が終了しません')


def config(**kwargs):
    return EvaluationRequest(participants=['Random','Heuristic'],opponents=[{'name':'RH','strategies':['Random','Heuristic']},{'name':'GS','strategies':['Greedy','ScoreAware']}],**kwargs)


def test_multi_opponent_independent_deals_storage_repro_and_budget_rejection(tmp_path):
    jobs,definitions,arena=setup(tmp_path)
    try:
        request=config();a=wait(jobs,jobs.submit(request)['id']);b=wait(jobs,jobs.submit(request)['id'])
        assert a['status']==b['status']=='completed' and a['completed_games']==48
        assert a['config_hash']==b['config_hash']
        assert a['fresh_deals']==[True,True] and b['fresh_deals']==[False,False]
        assert a['opponent_novelty']==[True,True] and b['opponent_novelty']==[False,False]
        assert all(r['report']['comparisons'][0]['fixed_evidence']['independent_deals']==2 for r in a['reports'])
        assert [r['report']['comparisons'][0]['fixed_evidence']['mean'] for r in a['reports']]==[r['report']['comparisons'][0]['fixed_evidence']['mean'] for r in b['reports']]
        assert a['integrated'] is None and len(a['recommendations'])>=2
        recommendation=EvaluationRequest.model_validate(a['recommendations'][0]['execution_request'])
        assert recommendation.seed_partition=='development' and recommendation.deals==10
        assert estimate_evaluation(recommendation,definitions)['games']<=360
        assert len(a['reports'][0]['report']['efficiency'])==1
        assert jobs.store.get(a['id'])['config_hash']==a['config_hash']
        record=arena.get(a['reports'][0]['arena_id'],True)
        changed=deepcopy(record);changed['results'][0]['strategy_version']='wrong'
        invalid=analyze_arena(changed,request,fixed_complete=True,confirmatory=True)
        assert invalid['comparisons'][0]['fixed_evidence']['independent_deals']<2
        assert invalid['comparisons'][0]['fixed_evidence']['decision']=='hold'
        weighted=wait(jobs,jobs.submit(config(weights=[.5,.5]))['id'])
        assert weighted['integrated'][0]['evidence']['independent_deals']==2
        assert weighted['integrated'][0]['evidence']['decision']=='hold'
        bad=EvaluationRequest(participants=['Random','budget_rollout'],opponents=[{'name':'RH','strategies':['Random','Heuristic']}],deals=1,include_expensive=True)
        r=wait(jobs,jobs.submit(bad)['id'])
        assert not r['reports'][0]['report']['comparisons'][0]['matching']['comparable']
        assert r['reports'][0]['report']['comparisons'][0]['fixed_evidence']['mean'] is None
    finally:jobs.close();arena.close()


def test_ablation_definitions_and_complete_factorial_analysis(tmp_path):
    jobs,definitions,arena=setup(tmp_path)
    try:
        for family in ('reserve_ablation','adaptive_ablation'):
            values=ablation_definitions(family)
            for d in values:definitions.add(d)
            assert len({d.definition_hash for d in values})==4
            request=EvaluationRequest(participants=[d.reference for d in values],purpose=family,opponents=[{'name':'RH','strategies':['Random','Heuristic']}],deals=1)
            r=wait(jobs,jobs.submit(request)['id'])
            assert r['status']=='completed' and r['completed_games']==24
            ablation=r['reports'][0]['report']['ablation']
            assert ablation['interaction']['independent_deals']==1 and ablation['interaction']['decision']=='hold'
            assert ablation['combined']['mean']==pytest.approx(ablation['factor_a']['mean']+ablation['factor_b']['mean']+ablation['interaction']['mean'])
    finally:jobs.close();arena.close()


@pytest.mark.parametrize('change',[{'evaluation_mode':'sequential'},{'seed_partition':'final'},{'deals':True},{'weights':[.2,.2]},{'weights':[-1,2]},{'opponents':[{'name':'a','strategies':['Random','Random']},{'name':'b','strategies':['Random','Random']}]}])
def test_invalid_contracts_rejected(change):
    with pytest.raises(ValueError):EvaluationRequest.model_validate({**config().model_dump(mode='json'),**change})


def test_api_planning_ablation_progress_export_and_cancel(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite')) as client:
        p=client.post('/api/evaluation/planning',json={'observed_deals':2,'sd_difference':1}).json()
        assert p['status']=='pilot_required' and p['estimated_total'] is None
        request=client.post('/api/evaluation/ablation/reserve_ablation',json={}).json()
        assert len(request['participants'])==4
        estimate=client.post('/api/evaluation/estimate',json=request).json();assert estimate['games']==96
        r=client.post('/api/evaluation/studies',json=request).json();identifier=r['id']
        client.post(f'/api/evaluation/studies/{identifier}/cancel',json={})
        for _ in range(500):
            result=client.get(f'/api/evaluation/studies/{identifier}/export').json()
            if result['status']!='running':break
            time.sleep(.01)
        assert result['status']=='cancelled'
        assert all(c['fixed_evidence']['decision']=='hold' for r in result['reports'] for c in r['report']['comparisons'])
        assert client.get('/api/evaluation/studies').json()[0]['id']==identifier
        assert client.post('/api/evaluation/estimate',json={**request,'evaluation_mode':'sequential'}).status_code==422


def test_budget_gate_and_posthoc_analysis_not_confirmatory(tmp_path):
    jobs,definitions,arena=setup(tmp_path)
    try:
        request=config(deals=1)
        r=wait(jobs,jobs.submit(request)['id'])
        record=arena.get(r['reports'][0]['arena_id'],True)
        result=analyze_arena(record,request,fixed_complete=True)
        assert all(c['fixed_evidence']['decision']=='hold' for c in result['comparisons'])
        with pytest.raises(ValueError):estimate_evaluation(config(deals=20),definitions)
        with pytest.raises(ValueError):EvaluationRequest.model_validate({**request.model_dump(mode='json'),'alpha':1e-100})
        with pytest.raises(ValueError):EvaluationRequest.model_validate({**request.model_dump(mode='json'),'purpose':'reserve_ablation'})
    finally:jobs.close();arena.close()


def test_weighted_blocks_follow_plan_order_across_decimal_seed_boundary(tmp_path):
    jobs,definitions,arena=setup(tmp_path)
    try:
        request=config(weights=[.5,.5],start_offset=999)
        r=wait(jobs,jobs.submit(request)['id'])
        samples=[report['report']['samples'][0] for report in r['reports']]
        blocks=[sum(.5*s[str(plan['deal_seeds'][index])] for s,plan in zip(samples,r['plans'])) for index in range(2)]
        assert r['integrated'][0]['evidence']['sd']==pytest.approx(float(np.std(blocks,ddof=1)))
    finally:jobs.close();arena.close()
