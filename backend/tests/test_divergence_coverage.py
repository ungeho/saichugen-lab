from copy import deepcopy
from pathlib import Path
import json
import pytest
from strategy_arena.experiments.divergence_coverage import score_class,select_coverage,coverage_report,audit_coverage,anomalies
from strategy_arena.experiments.noise_lab import StudyConfig,StudyJobs,study_estimate
from strategy_arena.experiments.evolution import digest
from strategy_arena.experiments.campaign_analysis import FROZEN_MODEL_HASH
from strategy_arena.experiments.evidence_lab import EvidenceLab
from test_campaign import campaign_config,evidence
from test_design_lab import setup
from test_middle_lab import wait


def config(factory,series='N',**kw):
    c=factory()
    return StudyConfig(**{**c.model_dump(),'revision':'phase42','collection_series':series,'coverage_targets':[] if series=='N' else ['highest'],**kw})


def records(c,scores=(3,1,2)):
    return [{'deal_id':str(c.start_offset),'deal_hash':'d','position_hash':str(i)+str(player),'turn':14,'period':'final_round',
        'source':source,'player':player,'game_scores':list(scores),'stratum':{'class':score_class(scores,player)}}
        for i,source in enumerate(c.collectors) for player in range(3)]


@pytest.mark.parametrize('scores,player,expected',[([3,1,2],0,'highest'),([3,1,2],1,'lowest'),([3,1,2],2,'strict_middle'),([3,1,1],0,'tie'),([2,2,2],1,'tie')])
def test_score_class_strict_and_all_ties_separate(scores,player,expected):assert score_class(scores,player)==expected


def test_natural_tuple_not_scores_or_evaluations(campaign_config):
    c=config(campaign_config);rs=records(c);a,slots=select_coverage(rs,c)
    assert len(a)==1 and a[0]['source']=='Random' and a[0]['player']==0
    changed=deepcopy(rs)
    for r in changed:r.update(game_scores=[0,0,0],gap=100,final_reward=-999,diverged=True)
    b,_=select_coverage(list(reversed(changed)),c)
    assert a[0]['position_hash']==b[0]['position_hash'] and slots[0]['requested_class'] is None


def test_duplicate_observation_origins_preserve_fixed_source(campaign_config):
    c=config(campaign_config);r=records(c)[0];r['origins']=[{k:r[k] for k in ('deal_id','deal_hash','source','player','turn')}];r['source']='Heuristic'
    selected,_=select_coverage([r],c);assert selected[0]['source']=='Random'


def test_s_targets_missing_and_bounded_pool(campaign_config):
    c=config(campaign_config,'S');selected,slots=select_coverage(records(c),c)
    assert len(selected)==1 and slots[0]['selected_class']=='highest' and slots[0]['candidate_observations']==15
    selected,slots=select_coverage(records(c,(3,3,1)),c)
    assert selected==[] and slots[0]['status']=='collection_missing'


def test_n_s_config_and_plan_separation(campaign_config):
    n=config(campaign_config);s=config(campaign_config,'S');assert n.model_dump()!=s.model_dump()
    with pytest.raises(ValueError):StudyConfig(**{**n.model_dump(),'coverage_targets':['highest']})
    with pytest.raises(ValueError):StudyConfig(**{**s.model_dump(),'coverage_targets':[]})
    with pytest.raises(ValueError):StudyConfig(**{**n.model_dump(),'revision':'phase41'})
    assert study_estimate(s)['completion_forecast']['warnings']!=study_estimate(n)['completion_forecast']['warnings']
    assert study_estimate(n)['completion_forecast']['model_hash']==study_estimate(s)['completion_forecast']['model_hash']


def value(factory,evidence,series='S'):
    c=config(factory,series,deals=2,max_positions=2,campaign_periods=['final_round','final_round'],coverage_targets=['highest','tie'] if series=='S' else [])
    p=deepcopy(evidence);p['player']=0;p['adaptive'].update(revision='phase42',collection_series=series)
    plan={'series':series};return {'id':'test','config':c.model_dump(mode='json'),'status':'Completed','positions':[p],'runtime_measurements':[],
        'snapshot':{'study_plan':plan,'study_plan_hash':digest(plan),'deal_hashes':['d','missing']},'elapsed_seconds':1,'result_hash':'saved',
        'collection_summary':{'independent_deals':2,'coverage_slots':[{'status':'selected','deal_hash':'d','position_hash':'p','ordinal':0},{'status':'collection_missing','deal_hash':'missing','position_hash':None,'ordinal':1}]}}


def test_missing_s_complete_but_not_natural_primary(campaign_config,evidence):
    v=value(campaign_config,evidence);assert audit_coverage(v)['primary_finalized']
    r=coverage_report(v);assert r['primary'] is None and r['selected_sample_summary'] is not None
    assert r['extraction_success']=={'selected':1,'requested':2,'rate':.5} and r['completion_counts']['collection_missing']==1
    assert all(x['collection_series']=='S' for x in r['partial_evidence'])
    n=value(campaign_config,evidence,'N');assert not audit_coverage(n)['primary_finalized'] and coverage_report(n)['primary'] is None


def test_no_early_stop_divergence_is_anomaly(campaign_config,evidence):
    v=value(campaign_config,evidence);r=next(x for x in v['positions'][0]['adaptive']['rows'] if x['method']=='Gap-Adaptive')
    r['selected_card']=next(x['card'] for x in r['candidates'] if x['card']!=r['selected_card']);r['early_stop']=False
    assert anomalies(v['positions']);report=coverage_report(v)
    assert not report['primary_finalized'] and report['anomalies']
    assert any(r['category']=='anomaly_without_early_stop' for r in report['partial_evidence'])


def test_mixing_rejected_and_partial_hidden(campaign_config,evidence):
    v=value(campaign_config,evidence);v['positions'][0]['adaptive']['collection_series']='N'
    with pytest.raises(ValueError):coverage_report(v)
    v=value(campaign_config,evidence);v['status']='TimedOut';r=coverage_report(v)
    assert r['primary'] is None and r['selected_sample_summary'] is None and r['partial_evidence']


def test_frozen_public_artifact_unchanged():
    m=json.loads((Path(__file__).parents[2]/'configs/calibration/phase40-frozen.json').read_text(encoding='utf-8'))
    assert digest(m)==FROZEN_MODEL_HASH


def test_real_jobs_separate_plans_and_sqlite_missing(tmp_path,campaign_config,monkeypatch):
    import strategy_arena.experiments.noise_lab as module
    from strategy_arena.experiments.runtime_analysis import environment
    design,ev,arena=setup(tmp_path);lab=StudyJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        c=config(campaign_config);env=environment(c);c.calibration.environment={k:env[k] for k in ('os','cpu','python')};monkeypatch.setattr(module,'FROZEN_MODEL_HASH',digest(c.calibration.model_dump(mode='json')))
        n=lab.register(c);s=lab.register(c.model_copy(update={'collection_series':'S','coverage_targets':['highest'],'start_offset':42001}))
        assert n['snapshot']['study_plan_hash']!=s['snapshot']['study_plan_hash']
        with pytest.raises(ValueError):lab.register(c.model_copy(update={'collection_series':'S','coverage_targets':['highest']}))
        lab.start(n['id'],n['condition_hash']);n=wait(lab,n['id']);assert n['status']=='Completed' and n['coverage_evidence']['primary']
        assert next(r for r in n['coverage_evidence']['primary'] if r['method']=='Gap-Adaptive')['divergence_interval'][1]>0
        def missing(records,c):return [],[{'ordinal':0,'deal_id':str(c.start_offset),'period':'final_round','status':'collection_missing','position_hash':None,'deal_hash':None}]
        monkeypatch.setattr(module,'select_coverage',missing)
        lab.start(s['id'],s['condition_hash']);s=wait(lab,s['id']);assert s['status']=='Completed',s.get('error')
        assert s['coverage_evidence']['series_completed'] and not s['coverage_evidence']['primary_finalized'] and s['coverage_evidence']['primary'] is None
        assert s['coverage_evidence']['completion_counts']['collection_missing']==1
        assert lab.get(n['id'])['coverage_evidence']==n['coverage_evidence']
    finally:lab.close();design.close();ev.close();arena.close()
