from copy import deepcopy
import json
from pathlib import Path
import pytest
from strategy_arena.experiments.matched_lab import MatchedConfig,MatchedJobs,matched_estimate
from strategy_arena.experiments.matched_analysis import matched_select,matched_report,legal_bucket
from strategy_arena.experiments.storage_efficiency import StorageSpec,evidence,encode,case,fault,run_storage
from strategy_arena.experiments.boundary_analysis import boundary_records
from strategy_arena.experiments.evolution import digest
from strategy_arena.experiments.evidence_lab import EvidenceLab
from strategy_arena.experiments.runtime_analysis import environment
from strategy_arena.experiments.stratification_lab import collect
from test_campaign import campaign_config,evidence as old_evidence
from test_boundary import job
from test_design_lab import setup
from test_middle_lab import wait


@pytest.fixture
def config(campaign_config,monkeypatch):
    import strategy_arena.experiments.boundary_lab as module
    m=campaign_config().calibration;monkeypatch.setattr(module,'FROZEN_MODEL_HASH',digest(m.model_dump(mode='json')))
    return lambda **kw:MatchedConfig(calibration=m,turns=[14],max_positions=2,positions_per_deal=2,campaign_periods=['final_round']*2,**kw)


def test_assigned_tuple_selection_no_outcome_feedback(config):
    c=config();rs,_,_=collect(c);a,s,cov=matched_select(rs,c);copy=deepcopy(rs)
    for r in copy:r.update(final_reward=999,gap=999,diverged=True)
    b,slots,_=matched_select(list(reversed(copy)),c)
    assert [r['position_hash'] for r in a]==[r['position_hash'] for r in b] and s==slots
    assert len(cov)==80 and all(r['source']=='Random' and r['player'] in (0,1,2) for r in a)
    missing=matched_select([],c)[1];assert len(missing)==2 and all(r['status']=='collection_missing' for r in missing)


def test_h1_features_do_not_use_future_values(config,old_evidence):
    c=config();v=job(old_evidence);v['config']=c.model_dump(mode='json');v['collection_summary']={};v['positions'][0]['deal_id']=str(c.start_offset)
    rs,_=boundary_records([v]);a=matched_report(v,rs,True)
    modified=deepcopy(rs)
    for r in modified:
        if r['checkpoints']['128']:r['checkpoints']['128']['selected_card']={'rank':13,'suit':3};r['checkpoints']['128']['top_gap']=999
        r['independent_reward']=999
    b=matched_report(v,modified,True)
    assert [(r['gap16'],r['small_gap']) for r in a['h1_records']]==[(r['gap16'],r['small_gap']) for r in b['h1_records']]
    assert all(r['reason']=='not_evaluated' for r in a['pairs'] if not r['matched'])
    assert legal_bucket(3)==legal_bucket(7) and legal_bucket(9)!=legal_bucket(7)


def test_h1_intermediate_change_and_return_is_not_endpoint_change(config,old_evidence):
    c=config();v=job(old_evidence);v['config']=c.model_dump(mode='json');v['positions'][0]['deal_id']=str(c.start_offset)
    rs,_=boundary_records([v]);rs=[r for r in rs if r['method']=='Fixed']
    for r in rs:
        r['leader_changes']=2;r['checkpoints']['16']['top_gap']=0;r['checkpoints']['128']['selected_card']=r['checkpoints']['16']['selected_card']
    report=matched_report(v,rs,True);g=next(r for r in report['h1_summary'] if r['small_gap'])
    assert g['leader_change_rate']['mean']==1 and g['endpoint_change_rate']['mean']==0


def test_storage_conditions_same_logical_evidence_and_wal(tmp_path):
    s=StorageSpec();logical=evidence(s);hashes=set();commits={}
    for i,(freq,batch) in enumerate(((1,1),(4,4),(12,12))):
        r=case(tmp_path/(str(i)+'.sqlite'),'plan',logical,encode(logical,512),freq,batch,lambda:None,s.db_limit_bytes)
        hashes.add(r['evidence_hash']);commits[freq]=r['commit_count'];assert r['integrity']=='ok' and r['wal_bytes']>0 and r['payload_bytes']==[512]*12
    assert hashes=={digest(logical)} and commits=={1:12,4:3,12:1}
    assert [json.loads(x)['evidence'] for x in encode(logical,4096)]==logical


@pytest.mark.parametrize('freq,expected,lost',[(1,7,0),(4,4,3),(12,0,7)])
def test_isolated_process_fault_restore_and_idempotency(tmp_path,freq,expected,lost):
    s=StorageSpec();logical=evidence(s);r=fault(tmp_path.resolve(),'plan',logical,encode(logical,4096),freq,4,7,lambda:None)
    assert len(r['committed_ids'])==expected and len(r['uncommitted_lost_ids'])==lost
    assert r['not_yet_generated']==list(range(7,12)) and r['evidence_hash_after_resume']==digest(logical) and r['duplicates_after_retry']==0 and r['integrity']=='ok'


def test_storage_limits_and_seed_precision(tmp_path):
    for fields in ({'payload_seed':str(2**64)},{'sizes':[1,4096,32768]},{'frequencies':[1,4,8]},{'crash_after':12},{'repeats':100}):
        with pytest.raises(ValueError):StorageSpec(**fields)
    s=StorageSpec(payload_seed=str(2**64-1));assert all(r['seed']==str(2**64-1) for r in evidence(s))
    def stop():raise InterruptedError('Cancelled')
    result={}
    with pytest.raises(InterruptedError):run_storage(s,tmp_path,'plan',result,stop)
    assert result['rows']==[] and not result.get('complete')


def test_active_fault_child_cancel_and_size_cap_are_local(tmp_path,monkeypatch):
    import strategy_arena.experiments.storage_efficiency as module
    captured=[];original=module.subprocess.Popen
    def launch(*args,**kw):
        child=original(*args,**kw);captured.append(child);return child
    monkeypatch.setattr(module.subprocess,'Popen',launch)
    spec=StorageSpec();logical=evidence(spec);payloads=encode(logical,512)
    def cancel():raise InterruptedError('Cancelled')
    with pytest.raises(InterruptedError):fault(tmp_path.resolve(),'plan',logical,payloads,4,4,7,cancel)
    assert len(captured)==1 and captured[0].poll() is not None
    with pytest.raises(InterruptedError,match='SizeLimitExceeded'):case(tmp_path/'bounded.sqlite','plan',logical,payloads,1,1,lambda:None,1)


def test_matched_config_budget_and_series_separation(config):
    c=config();assert matched_estimate(c)['derived_games_upper']==9792
    for fields in ({'matched_sources':['Random','Heuristic']},{'matched_scores':['highest','highest']},{'gap_threshold':.6},{'calibration':None}):
        with pytest.raises(ValueError):MatchedConfig(**{**c.model_dump(),**fields})
    e=MatchedConfig(matched_series='E');assert matched_estimate(e)['derived_games_upper']==0
    with pytest.raises(ValueError):MatchedConfig(matched_series='E',calibration=c.calibration)


def test_real_jobs_d_e_hash_reproduction_cancel_and_old_data(tmp_path,config,old_evidence,monkeypatch):
    import strategy_arena.experiments.boundary_lab as module
    design,ev,arena=setup(tmp_path);lab=MatchedJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        c=config();env=environment(c);c.calibration.environment={k:env[k] for k in ('os','cpu','python')};monkeypatch.setattr(module,'FROZEN_MODEL_HASH',digest(c.calibration.model_dump(mode='json')))
        old=job(old_evidence);old_id=design.store.save(old);d=lab.register(c);e=lab.register(MatchedConfig(matched_series='E',storage=StorageSpec(sizes=[256,512,1024],faults=False)))
        assert d['snapshot']['study_plan_hash']!=e['snapshot']['study_plan_hash']
        with pytest.raises(ValueError):lab.register(c)
        for v in (d,e):
            lab.start(v['id'],v['condition_hash']);v=wait(lab,v['id']);assert v['status']=='Completed',v.get('error')
        assert v['storage_evidence']['complete'] and len(v['storage_evidence']['result']['rows'])==81
        assert Path(v['storage_evidence']['result']['root']).is_relative_to(tmp_path.resolve()) and design.store.get(old_id)==old
        assert lab.get(d['id'])['matched_evidence']==lab.get(d['id'])['matched_evidence']
        pending=lab.register(MatchedConfig(matched_series='E'));assert lab.cancel(pending['id'])['status']=='Cancelled'
        assert not lab.get(pending['id'])['storage_evidence']['complete']
    finally:lab.close();design.close();ev.close();arena.close()
