from copy import deepcopy
import json
import pytest
from fastapi.testclient import TestClient

from test_rollout_quality import config, synthetic
from strategy_arena.experiments.rollout_quality import (BASELINE_COMMIT, KIND, StudyConfig, estimate,
    summarize_study, runtime_info)
from strategy_arena.experiments.quality_statistics import uncertainty, compare_saved, complete_deals
from strategy_arena.experiments.storage import ExperimentStore
from strategy_arena.game.rules import RULE_VERSION
from strategy_arena.game.rewards import REWARD_VERSION
from strategy_arena.api.app import create_app


def payload(cfg):
    rows=[]
    for seed in cfg.deal_seeds:
        rows+=synthetic(cfg,0,seed,1 if seed%2 else -1)
        rows+=synthetic(cfg,1,seed,2)
    required=['game/engine.py','game/rules.py','strategies/monte_carlo.py','strategies/baselines.py',
              'rollouts.py','inference.py','experiments/runner.py','experiments/rollout_quality.py']
    return {'experiment_kind':KIND,'status':'completed','config':cfg.model_dump(),'results':rows,
            'rule_version':RULE_VERSION,'reward_version':REWARD_VERSION,'baseline_commit':cfg.baseline_commit,
            'runtime':{'source_sha256':{k:'same' for k in required}},'positions':[], 'elapsed_seconds':0,
            'estimate':estimate(cfg),'error':None}


def test_ci_threshold_and_zero_variance():
    assert uncertainty([-1,1],42)['ci95'] is None
    assert uncertainty([-1,1]*5,42)['status']=='reference'
    info=uncertainty([-1,1]*10,42)
    assert info['status']=='available' and -1 <= info['ci95'][0] <= info['ci95'][1] <= 1
    assert info==uncertainty([-1,1]*10,42)
    zero=uncertainty([1]*20,42)
    assert zero['ci95'] is None and zero['status']=='zero_variance'


def test_large_cluster_counts_and_paired_matching():
    cfg=config(deal_seeds=list(range(20)));p=payload(cfg)
    summary=summarize_study(cfg,p['results'])
    assert summary['settings'][0]['games']==120
    assert summary['settings'][0]['independent_deals']==20
    assert summary['settings'][0]['uncertainty']['status']=='available'
    difference=summary['differences'][0]
    assert difference['independent_deals']==20 and difference['difference']==2
    assert difference['comparable']
    assert 1 <= difference['ci95'][0] <= difference['ci95'][1] <= 3


@pytest.mark.parametrize('field,value',[
    ('seed',999),('roles',[0,2,1]),('seat',2),('strategies',['Random']*3),
    ('rollout_parameters',{'trials':64}),('terminal_rewards',[0,0,0]),('strategy_version','future'),
])
def test_bad_match_metadata_excludes_entire_deal(field,value):
    cfg=config(deal_seeds=[0,1]);p=payload(cfg)
    # rotation0 is target at seat0; choose a conflicting value.
    p['results'][0][field]=value
    complete=complete_deals(cfg,p['results'],cfg.settings[0])
    assert set(complete)=={'1'}
    result=summarize_study(cfg,p['results'])
    assert result['differences'][0]['matched_deals']==['1']


def test_duplicate_rotation_excluded():
    cfg=config();p=payload(cfg);p['results'].append(deepcopy(p['results'][0]))
    assert not complete_deals(cfg,p['results'],cfg.settings[0])


@pytest.mark.parametrize('change', ['opponents','policy_seed','baseline_commit','rule','reward','information','sources','time'])
def test_incompatible_saved_studies_never_paired(change):
    a=config(deal_seeds=list(range(10)));b=a.model_dump()
    if change=='opponents':b['opponents']=['Heuristic','Heuristic']
    if change=='policy_seed':b['policy_seed']=99
    if change=='baseline_commit':b['baseline_commit']='8b380bec5e85f6368f7aa2f1c49db818f3abb160'
    if change=='time':b['settings'][1]['time_limit_ms']=100
    b=StudyConfig.model_validate(b);first=payload(a);second=payload(b)
    if change=='rule':second['rule_version']='other'
    if change=='reward':second['reward_version']='other'
    if change=='information':second['information_condition']='full'
    if change=='sources':second['runtime']['source_sha256']['game/engine.py']='different'
    result=compare_saved(first,second,a.settings[0].identifier,b.settings[1].identifier)
    assert not result['comparable'] and result['reasons']
    assert result['difference'] is None and result['ci95'] is None


def test_common_subset_is_explicit_not_all_deals():
    a=config(deal_seeds=list(range(20)));b=config(deal_seeds=list(range(10,30)))
    result=compare_saved(payload(a),payload(b),a.settings[0].identifier,b.settings[1].identifier)
    assert result['comparable'] and result['independent_deals']==10
    assert set(result['matched_deals'])=={str(i) for i in range(10,20)}
    assert len(result['first_only_deals'])==len(result['second_only_deals'])==10
    assert result['uncertainty']['status']=='reference'


def test_no_common_deals_or_missing_fingerprint():
    a=config(deal_seeds=[0]);b=config(deal_seeds=[1])
    assert not compare_saved(payload(a),payload(b),a.settings[0].identifier,b.settings[1].identifier)['comparable']
    p=payload(a);p['runtime']={}
    assert not compare_saved(p,p,a.settings[0].identifier,a.settings[1].identifier)['comparable']


def test_estimate_uses_measured_history_and_cpu():
    cfg=config(deal_seeds=list(range(10)));p=payload(cfg);p['runtime']=runtime_info()
    measured=estimate(cfg,[p])
    assert measured['estimated_seconds']==120
    assert measured['estimated_seconds_range']==[60,240]
    assert measured['estimated_storage_bytes']>0
    assert all(x['samples']==60 for x in measured['timing_sources'])
    unknown=cfg.model_dump();unknown['settings']=[{'trials':8,'continuation':'Heuristic'}]
    assert estimate(StudyConfig.model_validate(unknown))['estimated_seconds'] is None


def test_json_and_api_condition_comparison_preserves_saved_records(tmp_path):
    cfg=config(deal_seeds=list(range(10)));first=payload(cfg);second=payload(cfg)
    store=ExperimentStore(tmp_path/'compare.sqlite');a=store.save(first);b=store.save(second)
    before=store.get(a)
    assert json.loads(json.dumps(first))==store.get(a)
    with TestClient(create_app(store.path)) as client:
        result=client.post('/api/quality-studies/compare',json={'first_id':a,'second_id':b,
           'first_setting':cfg.settings[0].identifier,'second_setting':cfg.settings[1].identifier}).json()
        assert result['comparable'] and result['independent_deals']==10
        assert result['difference']==2
    assert store.get(a)==before
