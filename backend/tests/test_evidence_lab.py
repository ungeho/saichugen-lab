import json
import sqlite3
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from strategy_arena.api.app import create_app
from strategy_arena.experiments.evidence_lab import EvidenceLab,SeriesSpec,EvidenceSource,Projection,convergence,deal_identity
from strategy_arena.experiments.design_lab import PlanSpec
from strategy_arena.experiments.rollout_quality import runtime_info
from test_design_lab import setup,spec,wait


def run(lab,offset,n=2,policy_seed=None):
    data=spec().model_dump(mode='json');data.update(plan_id=f'evidence-{offset}');data['evaluation'].update(start_offset=offset,deals=n)
    if policy_seed is not None:data['evaluation']['policy_seed']=policy_seed
    data['budget'].update(max_independent_deals=20,max_games=360,allowed_seconds=120)
    s=PlanSpec.model_validate(data);lab.draft(s);v=lab.register(s.plan_id,1);lab.start(s.plan_id,1,v['plan_hash']);done=wait(lab,s.plan_id)
    assert done['state']=='Completed'
    return EvidenceSource(plan_id=s.plan_id,plan_version=1,plan_hash=v['plan_hash'])


def test_hand_calculated_convergence_small_and_zero_variance():
    rows=[{'difference':x,'deal_id':str(i),'elapsed_seconds':.5} for i,x in enumerate([1,-1,2,0])]
    curve=convergence(rows,.05,4)
    assert curve[-1]['mean']==.5 and curve[-1]['sd']==pytest.approx((5/3)**.5)
    assert curve[-1]['elapsed_seconds']==2 and curve[-1]['interval'] is None
    assert curve[1]['mean_change']==-1
    zero=convergence([{'difference':0,'deal_id':str(i),'elapsed_seconds':1} for i in range(10)],.05,1)[-1]
    assert zero['sd']==0 and zero['interval'][1]>0 and zero['width']>0


def test_deal_hash_stable_and_generator_required():
    hashes=runtime_info()['source_sha256']
    assert deal_identity(31,hashes)==deal_identity(31,hashes)
    assert deal_identity(31,hashes)!=deal_identity(32,hashes)
    with pytest.raises(ValueError):deal_identity(31,{'game/cards.py':'bad'})


def test_accumulation_duplicate_conditions_storage_projection_and_draft(tmp_path):
    design,jobs,arena=setup(tmp_path);lab=EvidenceLab(design.store,design)
    try:
        lab.create(SeriesSpec(series_id='test-series',hypothesis='追加配札で対応差を診断'))
        first=run(design,2000);second=run(design,2100)
        result=lab.add('test-series',1,first);result=lab.add('test-series',1,second)
        assert result['independent_deals']==4 and result['games']==96
        assert len(result['curves']['composition:0:target:0'])==4
        assert len(result['between']['1−0:target:0'])==4
        values=[s['difference'] for e in result['entries'] for s in e['samples']['composition:0:target:0']]
        assert result['curves']['composition:0:target:0'][-1]['mean']==pytest.approx(sum(values)/4)
        assert EvidenceLab(design.store,design).get('test-series',1)==result
        with pytest.raises(ValueError):lab.create(SeriesSpec(series_id='test-series',hypothesis='duplicate'))
        with pytest.raises(ValueError):lab.add('test-series',1,first)
        wrong=first.model_copy(update={'plan_hash':'0'*64})
        with pytest.raises(ValueError):lab.add('test-series',1,wrong)
        changed=run(design,2200,policy_seed=999)
        with pytest.raises(ValueError):lab.add('test-series',1,changed)
        projection=lab.project('test-series',1,Projection(additional_deals=10,seconds_per_deal=1,allowed_seconds=5))
        assert projection['additional_games']==240 and projection['additional_seconds']==20 and not projection['within_budget']
        assert projection['cumulative_distinct_deals']==14
        assert all(p['normal_approximate_full_width'] is None for p in projection['projections'].values())
        child=lab.draft('test-series',1);assert child['state']=='Draft'
        # 異なる実験IDでも同じ実配札の証拠は拒否する。
        original=lab.extract
        fake=deepcopy(result['entries'][0]);fake.pop('entry_hash');fake['evaluation_id']='different-id'
        lab.extract=lambda _:fake
        with pytest.raises(ValueError,match='重複'):lab.add('test-series',1,second)
        lab.extract=original
        with sqlite3.connect(design.store.path) as db:
            raw=design.store.get(result['entries'][0]['evaluation_id']);raw['elapsed_seconds']+=1
            db.execute('UPDATE experiments SET payload=? WHERE id=?',(json.dumps(raw),result['entries'][0]['evaluation_id']))
        assert lab.get('test-series',1)['state']=='Invalidated'
    finally:design.close();jobs.close();arena.close()


def test_historical_result_and_seed_separation(tmp_path):
    design,jobs,arena=setup(tmp_path);lab=EvidenceLab(design.store,design)
    try:
        first=run(design,3000);view=design.get(first.plan_id,1)
        eid=next(e['evaluation_id'] for e in view['events'] if e['state']=='Running')
        source=EvidenceSource(evaluation_id=eid,origin='historical_exploratory')
        lab.create(SeriesSpec(series_id='past-series',hypothesis='過去の探索結果'))
        result=lab.add('past-series',1,source)
        assert result['entries'][0]['plan_hash'] is None
        with pytest.raises(ValueError):EvidenceSource(evaluation_id=eid,origin='new_pilot')
        with pytest.raises(ValueError):lab.add('past-series',1,first.model_copy(update={'origin':'confirmatory'}))
    finally:design.close();jobs.close();arena.close()


def test_api_empty_export_and_invalid_source(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite')) as client:
        s={'series_id':'api-series','hypothesis':'収束を診断'}
        assert client.post('/api/evidence/series',json=s).status_code==201
        url='/api/evidence/series/api-series/1'
        assert client.get(url+'/export').json()['state']=='exploratory_diagnostic'
        assert len(client.get('/api/evidence/series').json())==1
        assert client.post(url+'/entries',json={'evaluation_id':'missing','origin':'historical_exploratory'}).status_code==404
        assert client.post(url+'/projection',json={'additional_deals':0}).status_code==422
        assert client.post(url+'/draft',json={}).status_code==422

def test_projection_with_enough_samples_and_budget_counts_compositions():
    lab=EvidenceLab.__new__(EvidenceLab)
    lab.get=lambda *args:{'integrity_errors':[],'signature':{'compositions':[{},{}],'strategies':[{},{}],'deal_layout':'shared'},'elapsed_seconds':20,'entries':[{'samples':{'composition:0:target:0':[{}]*10,'composition:1:target:0':[{}]*10}}],'curves':{'a':[{'n':10,'sd':2}]},'independent_deals':10}
    value=lab.project('test',1,Projection(additional_deals=6,seconds_per_deal=1,allowed_seconds=12))
    assert value['additional_seconds']==12 and value['within_budget']
    assert value['projections']['a']['normal_approximate_full_width']==pytest.approx(1.96)
    assert value['cumulative_distinct_deals']==16
