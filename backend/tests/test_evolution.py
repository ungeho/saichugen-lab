from datetime import datetime, timezone
from copy import deepcopy
import json
import time
import pytest
from fastapi.testclient import TestClient
from strategy_arena.strategies.declarative import DefinitionStore, builtin_definitions, StrategyDefinition
from strategy_arena.experiments.storage import ExperimentStore
from strategy_arena.experiments.arena import arena_jobs
from strategy_arena.experiments.evolution import Evolution, EvolutionRequest, Generation, StageRequest, Adoption, Criteria, generate, behavior, assessment
from strategy_arena.api.app import create_app


def generation(parent, **kw):
    return Generation(parent=parent.reference,created_at=datetime(2026,10,13,tzinfo=timezone.utc),**kw)


def setup(tmp_path,deals=2):
    store=ExperimentStore(tmp_path/'evolution.sqlite');definitions=DefinitionStore(store.path);jobs=arena_jobs(store)
    parent=definitions.get('codex_reserve@1.0.0')
    children=generate(parent,generation(parent))
    for d in children:definitions.add(d)
    service=Evolution(store,definitions,jobs)
    request=EvolutionRequest(parent=parent.reference,children=[d.reference for d in children],deals=deals,hypothesis='現在ラウンドの取り逃しを減らせるか',expected_effect='報酬の改善',side_effects='将来の選択肢を失う')
    result=service.create(request)
    return service,definitions,jobs,result


def finish(service,identifier,stage):
    for _ in range(500):
        view=service.get(identifier)
        if view['stages'][stage]['result']['status'] not in ('running','cancelling'):return view
        time.sleep(.01)
    raise AssertionError('評価が終わりません')


@pytest.mark.parametrize('operation',['weight','toggle','add_rule','search'])
def test_generation_reproducible_unique_parent_immutable(operation):
    parent=next(d for d in builtin_definitions() if d.id=='codex_reserve');before=parent.model_dump_json()
    r=generation(parent,count=1,operations=[operation])
    a=generate(parent,r);b=generate(parent,r)
    assert [d.definition_hash for d in a]==[d.definition_hash for d in b]
    assert behavior(a[0])!=behavior(parent) and a[0].parent.definition_hash==parent.definition_hash
    assert parent.model_dump_json()==before


def test_rule_and_budget_generation_and_limits():
    parent=next(d for d in builtin_definitions() if d.id=='codex_adaptive_theorist')
    for operation in ('rule_weight','remove_rule'):
        assert len(generate(parent,generation(parent,count=1,operations=[operation])))==1
    data=parent.model_dump(mode='json');data.pop('definition_hash');data.update(selection='theory_search',total_budget=32)
    search=StrategyDefinition.model_validate(data)
    assert generate(search,generation(search,count=1,operations=['budget']))[0].total_budget in (16,48)
    for change in ({'count':5},{'delta':2.},{'operations':['python']},{'seed':-1}):
        with pytest.raises(ValueError):generation(parent,**change)
    with pytest.raises(ValueError):generate(parent,generation(parent,count=4,operations=['search']))


def test_development_validation_storage_selection_and_no_adoption(tmp_path):
    service,definitions,jobs,r=setup(tmp_path)
    try:
        identifier=r['id'];refs=[c['reference'] for c in r['candidates']]
        with pytest.raises(ValueError):service.start(identifier,'validation',StageRequest(children=refs))
        service.start(identifier,'development',StageRequest(children=refs));dev=finish(service,identifier,'development')
        assert all(c['state']=='Development Tested' for c in dev['candidates'])
        assert all(c['independent_deals']==2 for c in dev['stages']['development']['comparisons'].values())
        with pytest.raises(ValueError):service.start(identifier,'development',StageRequest(children=refs))
        service.start(identifier,'validation',StageRequest(children=refs[:1]));validation=finish(service,identifier,'validation')
        assert validation['candidates'][0]['state']=='Inconclusive'
        assert validation['candidates'][1]['state']=='Development Tested'
        assert validation['stages']['development']['result']['config']['deal_seeds']==[300,301]
        assert validation['stages']['validation']['result']['config']['deal_seeds']==[1000300,1000301]
        with pytest.raises(ValueError):service.start(identifier,'final',StageRequest(children=refs[:1]))
        with pytest.raises(ValueError):service.decide(identifier,Adoption(child=refs[0],decision='Promoted',reason='勝ったから'))
        proposal=service.proposal(identifier);serialized=json.dumps(proposal)
        assert 'deal_seeds' not in serialized and 'matched_deals' not in serialized and '1000300' not in serialized
        assert 'results' not in proposal and 'final' not in proposal
        assert definitions.get(r['parent']['id']+'@'+r['parent']['version']).definition_hash==r['parent']['definition_hash']
        reloaded=Evolution(service.store,definitions,jobs).get(identifier)
        assert reloaded['config_hash']==r['config_hash'] and reloaded['changes']==r['changes']
        duplicate=service.create(EvolutionRequest.model_validate(r['settings']))
        assert duplicate['config_hash']==r['config_hash'] and duplicate['id']!=identifier
        decision=service.decide(identifier,Adoption(child=refs[0],decision='Rejected',reason='今回は検証の証拠が不足'))
        assert decision['candidates'][0]['state']=='Rejected'
        with pytest.raises(ValueError):service.decide(identifier,Adoption(child=refs[0],decision='Inconclusive',reason='戻す'))
    finally:jobs.close()


def test_invalid_lineage_and_behavior_duplicates(tmp_path):
    service,definitions,jobs,r=setup(tmp_path)
    try:
        data=deepcopy(r['settings']);data['children']=[r['settings']['children'][0]]*2
        with pytest.raises(ValueError):service.create(EvolutionRequest.model_validate(data))
        data['children']=['codex_score_planner@1.0.0']
        with pytest.raises(ValueError):service.create(EvolutionRequest.model_validate(data))
        with pytest.raises(ValueError):Criteria(min_deals=2)
        with pytest.raises(ValueError):service.start(r['id'],'validation',StageRequest(children=['missing@1.0.0']))
    finally:jobs.close()


def test_assessment_requires_ci_cost_and_opponent_coverage():
    comparison={'comparable':True,'reasons':[],'independent_deals':10,'difference':.5,'ci95':[.1,.8]}
    stage={'comparisons':{'child':comparison},'result':{'status':'completed','summary':{'settings':[{'reference':'parent','decision_ms':{'mean':1.}},{'reference':'child','decision_ms':{'mean':1.5}}]}}}
    assert assessment(Criteria(),stage,'child')['passed']
    for change in ({'min_deals':20},{'max_time_ratio':1.},{'min_opponent_compositions':2},{'min_difference':.2}):
        assert not assessment(Criteria(**change),stage,'child')['passed']
    stage['comparisons']['child']['ci95']=None
    assert not assessment(Criteria(),stage,'child')['passed']


def test_final_seed_one_use_and_explicit_promotion(tmp_path,monkeypatch):
    import strategy_arena.experiments.evolution as module
    service,definitions,jobs,r=setup(tmp_path,deals=1)
    # 統計関数の別テストとは分離し、通過済み証拠の状態遷移とseed予約を検証。
    monkeypatch.setattr(module,'assessment',lambda *args:{'passed':True,'reasons':[]})
    try:
        refs=[c['reference'] for c in r['candidates']]
        for stage in ('development','validation','final'):
            service.start(r['id'],stage,StageRequest(children=refs));finish(service,r['id'],stage)
        promoted=service.decide(r['id'],Adoption(child=refs[0],decision='Promoted',reason='事前基準を満たした証拠を確認'))
        assert promoted['candidates'][0]['state']=='Promoted'
        second=service.create(EvolutionRequest.model_validate(r['settings']))
        for stage in ('development','validation'):
            service.start(second['id'],stage,StageRequest(children=refs));finish(service,second['id'],stage)
        with pytest.raises(ValueError,match='使用済み|予約'):service.start(second['id'],'final',StageRequest(children=refs))
    finally:jobs.close()


def test_changed_evaluator_blocks_validation_evidence(tmp_path,monkeypatch):
    import strategy_arena.experiments.evolution as module
    service,definitions,jobs,r=setup(tmp_path,deals=1)
    monkeypatch.setattr(module,'assessment',lambda *args:{'passed':True,'reasons':[]})
    try:
        refs=[c['reference'] for c in r['candidates']]
        for stage in ('development','validation'):
            service.start(r['id'],stage,StageRequest(children=refs));finish(service,r['id'],stage)
        original=jobs.get
        validation_id=service.get(r['id'])['stages']['validation']['arena_id']
        def changed(identifier,*args):
            result=deepcopy(original(identifier,*args))
            if identifier==validation_id:result['runtime']['source_sha256']['game/engine.py']='changed'
            return result
        monkeypatch.setattr(jobs,'get',changed)
        assert all(not c['evidence']['validation']['passed'] for c in service.get(r['id'])['candidates'])
        with pytest.raises(ValueError):service.start(r['id'],'final',StageRequest(children=refs))
    finally:jobs.close()


def test_evolution_api_schema_import_export_and_cancel(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite')) as client:
        parent=next(d for d in builtin_definitions() if d.id=='codex_reserve')
        request=generation(parent,count=1).model_dump(mode='json')
        preview=client.post('/api/evolution/generate',json=request).json()
        assert preview['registered'] is False
        child=preview['candidates'][0]
        assert client.post('/api/evolution/import',json=child).status_code==201
        assert client.post('/api/evolution/import',json={**child,'shell':'echo'}).status_code==422
        config=EvolutionRequest(parent=parent.reference,children=[child['id']+'@'+child['version']],deals=20,hypothesis='仮説',expected_effect='効果',side_effects='副作用').model_dump(mode='json')
        r=client.post('/api/evolution/experiments',json=config).json();identifier=r['id']
        assert len(r['config_hash'])==64 and r['candidates'][0]['state']=='Candidate'
        stage=client.post(f'/api/evolution/experiments/{identifier}/stages/development',json={'children':config['children']}).json()
        arena_id=stage['stages']['development']['arena_id']
        client.post(f'/api/arena/studies/{arena_id}/cancel',json={})
        for _ in range(300):
            result=client.get(f'/api/evolution/experiments/{identifier}/export').json()
            if result['stages']['development']['result']['status'] not in ('running','cancelling'):break
            time.sleep(.01)
        assert result['stages']['development']['result']['status']=='cancelled'
        assert result['candidates'][0]['state']=='Candidate'
        assert client.get('/api/evolution/experiments').json()[0]['id']==identifier
