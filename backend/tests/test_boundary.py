from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import json,time
import pytest
from strategy_arena.experiments.boundary_analysis import boundary_records,boundary_summary,checkpoint_features,crossed_select,crossed_report
from strategy_arena.experiments.boundary_lab import BoundaryConfig,BoundaryJobs,boundary_estimate
from strategy_arena.experiments.stratification_lab import collect
from strategy_arena.experiments.budget_calibration import active_ledger,stage_span,breakdown
from strategy_arena.experiments.evolution import digest
from strategy_arena.experiments.evidence_lab import EvidenceLab
from strategy_arena.experiments.runtime_analysis import environment
from strategy_arena.game.rules import RULE_VERSION
from strategy_arena.game.rewards import REWARD_VERSION
from test_campaign import campaign_config,evidence
from test_design_lab import setup
from test_middle_lab import wait


@pytest.fixture
def config(campaign_config,monkeypatch):
    import strategy_arena.experiments.boundary_lab as module
    m=campaign_config().calibration
    monkeypatch.setattr(module,'FROZEN_MODEL_HASH',digest(m.model_dump(mode='json')))
    return lambda **kwargs:BoundaryConfig(calibration=m,max_positions=1,positions_per_deal=1,campaign_periods=['final_round'],**kwargs)


def job(evidence):
    return {'id':'past','status':'Completed','config':{'revision':'phase37','gap_threshold':.5,'uncertainty_z':2,'minimum_gap':.05},
        'snapshot':{'rule':RULE_VERSION,'reward':REWARD_VERSION},'positions':[deepcopy(evidence)]}


def test_checkpoints_ties_and_no_interpolation():
    t={'worlds':16,'selected_card':{'rank':2,'suit':0},'candidates':[{'card':{'rank':3,'suit':0},'reward':1},{'card':{'rank':2,'suit':0},'reward':1}]}
    f=checkpoint_features(t);assert f['top_gap']==f['minimum_pair_gap']==0 and f['ranking'][0]==t['selected_card']
    assert checkpoint_features(None) is None
    assert checkpoint_features({'worlds':32,'gap':.25})['top_gap'] is None


def test_quality_missing_checkpoints_and_independent_streams(evidence):
    v=job(evidence);rows,_=boundary_records([v]);assert {r['quality'] for r in rows}=={'Complete Comparable'}
    p=v['positions'][0];p['adaptive']['rows'][0]['trace']=[]
    rows,_=boundary_records([v]);assert all(t is None for t in rows[0]['checkpoints'].values())
    v['status']='TimedOut';assert {r['quality'] for r in boundary_records([v])[0]}=={'Partial Comparable'}
    p['adaptive']['stage_seeds']={'policy':'1','reference':'1','final':'2'}
    assert {r['quality'] for r in boundary_records([v])[0]}=={'Descriptive Only'}
    v['snapshot']['rule']='other';assert {r['quality'] for r in boundary_records([v])[0]}=={'Incompatible'}
    p['adaptive']['rows']=[r for r in p['adaptive']['rows'] if r['method']!='Fixed'];assert {r['quality'] for r in boundary_records([v])[0]}=={'Unknown'}


def test_historical_divergence_preserves_signed_reward_and_original(evidence):
    v=job(evidence);original=deepcopy(v);r=next(r for r in v['positions'][0]['adaptive']['rows'] if r['method']=='Gap-Adaptive')
    r['selected_card']=next(x['card'] for x in r['candidates'] if x['card']!=r['selected_card']);r['early_stop']=True;r['evaluations'][0]['minus_fixed']['mean']=1.375
    rows,_=boundary_records([v]);div=[r for r in rows if r['group']=='D'];assert div[0]['reward_difference']==1.375
    assert original['positions'][0]['adaptive']['rows']!=v['positions'][0]['adaptive']['rows']
    before=deepcopy(v);boundary_summary(rows);assert v==before


def test_phase37_recorded_divergence_example_not_a_new_simulation(evidence):
    v=job(evidence);p=v['positions'][0];p['adaptive']['stage_seeds']={'policy':'18446744073709551614','reference':'18446744073709551613','final':'18446744073709551612'}
    fixed=next(r for r in p['adaptive']['rows'] if r['method']=='Fixed');adaptive=next(r for r in p['adaptive']['rows'] if r['method']=='Gap-Adaptive')
    fixed['selected_card']={'rank':7,'suit':2};adaptive.update(selected_card={'rank':3,'suit':3},early_stop=True)
    adaptive['evaluations'][0]['minus_fixed']['mean']=1.375
    rows,_=boundary_records([v]);row=next(r for r in rows if r['method']=='Gap-Adaptive')
    assert row['diverged'] and row['reward_difference']==1.375 and row['stage_seeds']['policy']=='18446744073709551614'
    # 実保存データの再発見はローカル監査で別途実施。ここは形式/符号/64bit精度の回帰。


def test_deal_equal_weight_and_phase_separation(evidence):
    rs,_=boundary_records([job(evidence)]);r=rs[0];r['reward_difference']=1
    many=[deepcopy(r) for _ in range(9)]+[{**deepcopy(r),'deal_hash':'second','reward_difference':-1}]
    groups=boundary_summary(many)['groups'];assert groups[0]['features']['reward_difference']['mean']==0 and groups[0]['independent_deals']==2
    other={**deepcopy(r),'comparison_family':'other'};assert len(boundary_summary([r,other])['groups'])==2


def test_crossed_matrix_caps_and_missing(config):
    c=config();records,_,_=collect(c);a,cells=crossed_select(records,c)
    assert len(cells)==16 and len(a)==1 and sum(s['status']=='not_planned' for s in cells)==12
    assert len({r['position_hash'] for r in a})==len(a)
    a,missing=crossed_select([],c);assert a==[] and sum(x['status']=='collection_missing' for x in missing)==4


def test_measured_collection_semantics_and_exclusive_cost(config):
    c=config();a,obs,summary=collect(c);ledger={'rows':[],'stack':[]};token=active_ledger.set(ledger)
    try:
        start=time.perf_counter()
        with stage_span('collection'):b,obs2,summary2=collect(c,span=stage_span)
        cost=breakdown(ledger['rows'],time.perf_counter()-start)
    finally:active_ledger.reset(token)
    assert a==b and summary==summary2 and {k:asdict(v) for k,v in obs.items()}=={k:asdict(v) for k,v in obs2.items()}
    assert not cost['overlap_or_timer_error'];assert cost['measured_exclusive_wall_seconds']<=cost['total_wall_seconds']
    assert {'trajectory_generation','position_extraction','score_classification'}<=cost['stages'].keys()


def test_plan_limits_and_frozen_model(config):
    c=config();assert boundary_estimate(c)['derived_games_upper']==4896
    for changes in ({'gap_threshold':.6},{'budgets':[64]},{'repeats':2},{'reference_worlds':32},{'positions_per_deal':0},{'boundary_series':'M','turns':[10]},{'source_ids':['past']},{'campaign_periods':['middle']},{'calibration':None}):
        with pytest.raises(ValueError):BoundaryConfig(**{**c.model_dump(),**changes})
    assert json.loads((Path(__file__).parents[2]/'configs/calibration/phase40-frozen.json').read_text())['version']=='coverage-turn-rate-v2'


def test_real_jobs_c_m_b_storage_export_cancel_and_duplicate(tmp_path,config,evidence):
    design,ev,arena=setup(tmp_path);lab=BoundaryJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        c=config();env=environment(c);c.calibration.environment={k:env[k] for k in ('os','cpu','python')}
        import strategy_arena.experiments.boundary_lab as module
        old=module.FROZEN_MODEL_HASH;module.FROZEN_MODEL_HASH=digest(c.calibration.model_dump(mode='json'))
        try:
            n=lab.register(c);m=lab.register(BoundaryConfig(**{**c.model_dump(),'boundary_series':'M','start_offset':43001}))
            assert n['snapshot']['study_plan_hash']!=m['snapshot']['study_plan_hash']
            with pytest.raises(ValueError):lab.register(c)
            for v in (n,m):
                lab.start(v['id'],v['condition_hash']);v=wait(lab,v['id']);assert v['status']=='Completed',v.get('error');assert v['boundary_evidence']['complete']
                assert lab.get(v['id'])['boundary_evidence']==v['boundary_evidence']
                assert all(isinstance(s,str) for r in v['boundary_evidence']['records'] for s in r['stage_seeds'].values())
            trials=v['boundary_evidence']['measurement_trials'];assert len(trials)==12
            assert len({t['content_hash'] for t in trials if t['kind']=='storage'})==1
            past=job(evidence);pid=design.store.save(past);b=lab.register(BoundaryConfig(boundary_series='B',source_ids=[pid]));lab.start(b['id'],b['condition_hash']);b=wait(lab,b['id'])
            assert b['status']=='Completed' and b['boundary_evidence']['records'] and design.store.get(pid)==past
            pending=lab.register(BoundaryConfig(**{**c.model_dump(),'start_offset':43002}));assert lab.cancel(pending['id'])['status']=='Cancelled'
            assert not lab.get(pending['id'])['boundary_evidence']['complete']
            raw=design.store.get(n['id']);raw['snapshot']['study_plan']['series']='M';design.store.update(n['id'],raw)
            with pytest.raises(ValueError):lab.start(n['id'],n['condition_hash'])
        finally:module.FROZEN_MODEL_HASH=old
    finally:lab.close();design.close();ev.close();arena.close()


def test_failed_or_missing_run_does_not_fabricate_outcomes(tmp_path,config,monkeypatch):
    import strategy_arena.experiments.boundary_lab as module
    design,ev,arena=setup(tmp_path);lab=BoundaryJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        c=config();env=environment(c);c.calibration.environment={k:env[k] for k in ('os','cpu','python')};monkeypatch.setattr(module,'FROZEN_MODEL_HASH',digest(c.calibration.model_dump(mode='json')))
        good=lab.register(c)
        original=module.crossed_select
        monkeypatch.setattr(module,'crossed_select',lambda records,c:original([],c))
        lab.start(good['id'],good['condition_hash']);v=wait(lab,good['id']);assert v['status']=='Completed' and not v['positions']
        assert sum(x['missing'] for x in v['boundary_evidence']['crossed']['cells'])==4
        assert all(r['metrics']['reward_difference']['mean'] is None for r in v['boundary_evidence']['paired_outcomes'])
        bad=lab.register(BoundaryConfig(**{**c.model_dump(),'start_offset':43003}))
        def fail(*args,**kwargs):raise ValueError('検証用の収集失敗')
        monkeypatch.setattr(module,'collect',fail);lab.start(bad['id'],bad['condition_hash']);v=wait(lab,bad['id'])
        assert v['status']=='Failed' and not v['boundary_evidence']['complete'] and v['boundary_evidence']['paired_outcomes'] is None
        with pytest.raises(ValueError):lab.start(v['id'],v['condition_hash'])
    finally:lab.close();design.close();ev.close();arena.close()


def test_compact_history_keeps_default_api_compatible(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from strategy_arena.api.app import create_app
    from strategy_arena.experiments.noise_lab import StudyJobs
    with TestClient(create_app(tmp_path/'api.sqlite')) as client:
        old=client.post('/api/runtime-divergence/jobs',json={'start_offset':43400,'turns':[14],'max_positions':1,'models':['Random'],'budgets':[32]}).json()
        new=client.post('/api/runtime-divergence/jobs',json={'revision':'phase43','boundary_series':'B','source_ids':[old['id']]}).json()
        with monkeypatch.context() as patch:
            patch.setattr(StudyJobs,'history',lambda self:(_ for _ in ()).throw(AssertionError('詳細の再集約を呼ばない')))
            compact=client.get('/api/runtime-divergence/jobs?summary=true');assert compact.status_code==200
        assert {x['id'] for x in compact.json()}=={old['id'],new['id']} and len(compact.content)<1000
        assert all('positions' not in x and 'snapshot' not in x for x in compact.json())
        full=client.get('/api/runtime-divergence/jobs').json();assert len(full)==2 and all('positions' in x and 'snapshot' in x for x in full)
