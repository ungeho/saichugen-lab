from random import Random
from copy import deepcopy
import time,json,sqlite3
import pytest
from fastapi.testclient import TestClient
from strategy_arena.api.app import create_app
from strategy_arena.game.engine import Game
from strategy_arena.game.cards import deal
from strategy_arena.experiments.middle_analysis import evaluate_position,outcome_metrics,classify
from strategy_arena.experiments.middle_lab import MiddleConfig,MiddleJobs,middle_estimate
from strategy_arena.experiments.evidence_lab import EvidenceLab,SeriesSpec
from test_design_lab import setup


def position(turn=12):
    g=Game(42)
    for _ in range(turn):g.play(tuple(g.observe(p).hand[0] for p in range(3)))
    return g

def wait(lab,i):
    for _ in range(1000):
        v=lab.get(i)
        if v['status']!='Running':return v
        time.sleep(.01)
    raise AssertionError('未完了')


def test_observation_only_common_samples_seed_and_metrics():
    g=position();obs=g.observe(0);before=deepcopy(g.__dict__);cards=obs.legal_actions[:3]
    first=evaluate_position(obs,cards,('Random',)*3,12,18)
    assert first==evaluate_position(obs,cards,('Random',)*3,12,18)
    reverse=evaluate_position(obs,tuple(reversed(cards)),('Random',)*3,12,18)
    assert first['candidates']==list(reversed(reverse['candidates']))
    assert g.__dict__==before
    assert all(c['final_start_middle'] is None for c in first['candidates'])
    assert all(-2<=c['reward']<=2 and sum(c['round_result_distribution'].values())==12 for c in first['candidates'])
    for pair in first['reversals']:
        assert pair['immediate_a_minus_b']['mean']>0 and pair['reward_b_minus_a']['mean']>0
    assert first['paired'][0]['reward_b_minus_a']['independent_world_samples']==12
    # 実際の相手の残り札を入れ替えても本人の観測は同じ。
    hands,unused=deal(42);other=Game.from_deal((hands[0],hands[2],hands[1]),unused)
    # 初期観測だけで評価し、実際の相手手札は受け取らない。
    assert evaluate_position(Game(42).observe(0),Game(42).observe(0).hand[:2],('Random',)*3,2,5)==evaluate_position(other.observe(0),other.observe(0).hand[:2],('Random',)*3,2,5)


def test_final_round_boundary_score_gaps_and_rewards():
    g=position(11);obs=g.observe(0)
    while not g.finished:g.play(tuple(g.observe(p).hand[0] for p in range(3)))
    values=outcome_metrics(g,obs);history=g.observe(0).history;final=g.observe(0).game_scores
    assert values['immediate_middle']==(history[11].winner==0)
    assert values['opponent_gap_change']==abs(final[1]-final[2])-abs(obs.game_scores[1]-obs.game_scores[2])
    assert values['score_changes']==[final[i]-obs.game_scores[i] for i in range(3)]
    assert values['final_start_middle'] in (0,1)
    assert outcome_metrics(g,position(12).observe(0))['final_start_middle'] is None


def test_registration_hash_budget_seed_storage_links_and_no_overwrite(tmp_path):
    design,evaluation,arena=setup(tmp_path);lab=MiddleJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        c=MiddleConfig(reproduce=False,turns=[12],trials=2,validation_trials=10,max_validate=1,start_offset=19000,validation_offset=19000)
        r=lab.register(c)
        with pytest.raises(ValueError):lab.register(c)
        with pytest.raises(ValueError):lab.start(r['id'],'0'*64)
        lab.start(r['id'],r['condition_hash']);v=wait(lab,r['id']);assert v['status']=='Completed'
        assert len(v['positions'])==1 and v['positions'][0]['observation']['hand_sizes']==[5,5,5]
        assert lab.get(v['id'])==v
        before=deepcopy(design.store.get(v['id']))
        draft=lab.design_draft(v['id']);assert draft['state']=='Draft'
        lab.evidence.create(SeriesSpec(series_id='middle-ref',hypothesis='参照のみ'))
        assert lab.link_evidence(v['id'],'middle-ref',1)['aggregated'] is False
        series=lab.evidence.get('middle-ref',1);assert series['independent_deals']==0 and len(series['external_references'])==1
        assert design.store.get(v['id'])==before
        with sqlite3.connect(design.store.path) as db:
            altered=deepcopy(before);altered['positions'][0]['labels']=[];db.execute('UPDATE experiments SET payload=? WHERE id=?',(json.dumps(altered),v['id']))
        assert lab.get(v['id'])['status']=='Invalidated'
    finally:lab.close();design.close();evaluation.close();arena.close()


def test_limits_final_seed_and_cancel(tmp_path):
    with pytest.raises(ValueError):MiddleConfig(start_offset=2000000)
    with pytest.raises(ValueError):MiddleConfig(continuation=('monte_carlo_rollout',)*3)
    with pytest.raises(ValueError):MiddleConfig(turns=[12,12])
    assert middle_estimate(MiddleConfig())['independent_deals']==1
    design,evaluation,arena=setup(tmp_path);lab=MiddleJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        v=lab.register(MiddleConfig(reproduce=False,turns=[0],trials=64,start_offset=18000,validation_offset=18000))
        lab.start(v['id'],v['condition_hash']);lab.cancel(v['id']);assert wait(lab,v['id'])['status']=='Cancelled'
    finally:lab.close();design.close();evaluation.close();arena.close()


def test_api_register_export_reject_and_no_auto_run(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite')) as client:
        c={'reproduce':False,'turns':[14],'trials':2,'max_validate':0,'start_offset':18000}
        v=client.post('/api/middle/jobs',json=c).json();assert v['status']=='Registered'
        assert client.post('/api/middle/jobs/'+v['id']+'/start',json={'condition_hash':'0'*64}).status_code==422
        assert client.get('/api/middle/jobs/'+v['id']+'/export').json()['condition_hash']==v['condition_hash']
        assert client.post('/api/middle/jobs/'+v['id']+'/cancel',json={}).json()['status']=='Cancelled'

def test_paired_explanation_and_world_units_not_deal_counts():
    from strategy_arena.experiments.middle_analysis import presentation
    value={'immediate_a_minus_b':{'mean':.1,'independent_deals':32,'adjusted_alpha':.005,'reason':'独立配札'},'reward_b_minus_a':{'mean':0,'independent_deals':32,'adjusted_alpha':.005,'reason':'独立配札'},'status':'point_estimate_candidate'}
    result=presentation(value)
    assert result['status']=='paired_comparison' and '逆転はなし' in result['explanation']
    assert result['reward_b_minus_a']['independent_world_samples']==32
    assert 'independent_deals' not in result['reward_b_minus_a']
    assert value['status']=='point_estimate_candidate'
