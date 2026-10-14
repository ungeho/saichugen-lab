from copy import deepcopy
from dataclasses import asdict
from random import Random
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient
from strategy_arena.api.app import create_app
from strategy_arena.game.engine import Game
from strategy_arena.strategies.registry import create_strategy
from strategy_arena.experiments.stratification_analysis import (
    StrataDefinition, stratify, period, evaluate_stratified, case_flags,
    select_positions, cluster_summary,
)
from strategy_arena.experiments.stratification_lab import StratificationConfig, StratificationJobs, collect
from strategy_arena.experiments.evidence_lab import EvidenceLab
from test_design_lab import setup
from test_middle_lab import wait, position


def test_strict_middle_ties_asymmetry_and_size():
    d=StrataDefinition()
    s=stratify((1,5,9),1,d)
    assert s['strict_middle'] and s['equal_gaps'] and s['both_small']
    assert s['relation']=='balanced' and s['gap_total']==8
    assert stratify((1,8,10),1,d)['relation']=='upper_close'
    assert stratify((1,3,10),1,d)['relation']=='lower_close'
    assert stratify((0,10,20),1,d)['both_large']
    for scores in ((1,1,3),(1,3,3),(2,2,2)):
        for p in range(3):
            s=stratify(scores,p,d)
            assert s['class']=='tie' and not s['strict_middle']
    assert stratify((1,2,3),0,d)['class']=='lowest'
    assert stratify((1,2,3),2,d)['class']=='highest'
    assert [period(t) for t in (3,6,11,12,14)]==['early','middle','before_final_round','final_round_start','final_round']


def test_collection_reachable_dedup_and_observation_only():
    c=StratificationConfig(deals=1,turns=[0,12],max_positions=3,controls=1)
    records,obs,summary=collect(c)
    assert summary['scanned']==30 and summary['duplicates']>=12
    assert set(summary['by_source'])==set(c.collectors)
    assert len({r['deal_hash'] for r in records})==1
    for r in records:
        o=obs[r['position_hash']]
        assert len(o.hand)==17-o.turn and o.legal_actions==o.hand
        assert 'hands' not in asdict(o) and 'unused' not in asdict(o)
        assert len({card for h in o.history for card in h.cards})==3*o.turn
        # Independently replay the public history from the same legal deal.
        g=Game(int(r['deal_id']))
        for h in o.history:g.play(h.cards)
        assert g.observe(r['player'])==o
    assert records==collect(c)[0]


def test_selection_and_deal_cluster_not_position_independence():
    records,_,_=collect(StratificationConfig(deals=2,turns=[3,6,12]))
    a=select_positions(records,6,1,[3,6,12])
    assert a==select_positions(list(reversed(records)),6,1,[3,6,12])
    assert len({r['position_hash'] for r in a})==len(a)
    def row(deal,rev):return {'deal_hash':deal,'stratum':{'strict_middle':True,'relation':'balanced'},'search':{'reversals':[1] if rev else [],'case_b_candidates':[]}}
    s=cluster_summary([row('a',True),row('a',False),row('b',True)])[0]
    assert s['independent_deals']==2 and s['positions']==3
    assert s['deal_mean_reversal_fraction']==.75


def stable(value):
    v=deepcopy(value)
    for c in v['candidates']:c.pop('rollout_seconds')
    return v


def test_common_worlds_seed_card_order_and_metrics():
    g=position(11);o=g.observe(0);before=deepcopy(g.__dict__);cards=o.legal_actions[:3]
    a=evaluate_stratified(o,cards,('Random',)*3,4,17,100)
    b=evaluate_stratified(o,tuple(reversed(cards)),('Random',)*3,4,17,100)
    assert stable(a)==stable(evaluate_stratified(o,cards,('Random',)*3,4,17,100))
    assert stable(a)['candidates']==list(reversed(stable(b)['candidates']))
    assert g.__dict__==before
    for c in a['candidates']:
        assert sum(c['immediate_probabilities'])==1
        assert c['immediate_middle']==c['immediate_probabilities'][o.player]
        assert c['upper_gap_change']+c['lower_gap_change']==pytest.approx(c['opponent_gap_change'])
        assert sum(c['next_scores_distribution'].values())==4
        assert c['next_strict_middle']==c['final_start_strict_middle']
        assert -2<=c['reward']<=2
    assert all(c['final_start_strict_middle'] is None for c in evaluate_stratified(position().observe(0),position().observe(0).hand[:2],('Random',)*3,2,2,10)['candidates'])


def test_case_b_requires_every_condition_and_initial_strict():
    a={'immediate_middle':.8,'reward':0,'opponent_gap_change':1,'next_strict_middle':.2}
    b={'immediate_middle':.4,'reward':1,'opponent_gap_change':2,'next_strict_middle':.4}
    assert all(case_flags(a,b).values())
    assert not all(case_flags(a,b,False).values())
    assert not case_flags(a,{**b,'opponent_gap_change':0})['G2']
    assert not case_flags({**a,'opponent_gap_change':-2},{**b,'opponent_gap_change':-1})['G2']
    assert not case_flags(a,{**b,'reward':0})['G1']


def test_limits():
    for kw in ({'deals':9},{'controls':12},{'definition':{'small':10,'large':5}}, {'collectors':['Random','Random']},{'turns':[14,3]},{'continuation':('monte_carlo_rollout',)*3},{'trials':64,'max_positions':24}):
        with pytest.raises(ValueError):StratificationConfig(**kw)


def test_storage_hash_validation_seed_and_old_rows(tmp_path):
    design,ev,arena=setup(tmp_path);lab=StratificationJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        old=list(design.store.iter_experiments())
        c=StratificationConfig(deals=1,turns=[12],max_positions=2,controls=0,trials=2,validation_trials=10,max_validate=1,start_offset=29000,validation_offset=29000)
        v=lab.register(c)
        with pytest.raises(ValueError):lab.register(c)
        assert v['snapshot']['rotations']=='all-three-observers-per-collector-trajectory'
        with pytest.raises(ValueError):lab.start(v['id'],'x')
        lab.start(v['id'],v['condition_hash']);v=wait(lab,v['id'])
        assert v['status']=='Completed',v.get('error')
        assert v['positions'] and v['inventory']
        assert lab.get(v['id'])==v
        for p in v['positions']:
            if p['validation']:
                assert p['validation']['seed']!=p['search']['seed']
                val=p['validation']
                assert val['case_b_repeated']==(val['discovery_case_b'] and val['validation_case_b'])
        now=dict(design.store.iter_experiments())
        assert all(now[i]==r for i,r in old)
        raw=design.store.get(v['id']);raw['inventory'][0]['period']='tampered'
        with sqlite3.connect(design.store.path) as db:db.execute('UPDATE experiments SET payload=? WHERE id=?',(json.dumps(raw),v['id']))
        invalid=lab.get(v['id']);assert invalid['status']=='Invalidated' and invalid['inventory']==[] and invalid['positions']==[]
    finally:lab.close();design.close();ev.close();arena.close()


def test_api_estimate_export_and_cancel(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite')) as client:
        config={'deals':1,'turns':[14],'max_positions':2,'controls':0,'max_validate':0}
        assert client.post('/api/stratification/estimate',json=config).json()['collection_games']==5
        r=client.post('/api/stratification/jobs',json=config);assert r.status_code==201
        v=r.json()
        assert client.get('/api/middle/jobs/'+v['id']).status_code==404
        assert client.get('/api/stratification/jobs/'+v['id']+'/export').json()==v
        assert client.post('/api/stratification/jobs/'+v['id']+'/cancel',json={}).json()['status']=='Cancelled'


def test_running_cancel_is_not_completed(tmp_path):
    design,ev,arena=setup(tmp_path);lab=StratificationJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        c=StratificationConfig(deals=2,turns=[0,3,6],max_positions=2,controls=0,trials=64,max_validate=0,start_offset=31000)
        v=lab.register(c);lab.start(v['id'],v['condition_hash']);lab.cancel(v['id'])
        assert wait(lab,v['id'])['status']=='Cancelled'
    finally:lab.close();design.close();ev.close();arena.close()


def test_actual_opponent_hands_are_not_an_input():
    from strategy_arena.game.cards import deal
    hands,unused=deal(42)
    a=Game.from_deal(hands,unused);b=Game.from_deal((hands[0],hands[2],hands[1]),unused)
    assert a.observe(0)==b.observe(0)
    o=a.observe(0);cards=o.hand[:2]
    assert stable(evaluate_stratified(o,cards,('Random',)*3,2,3,10))==stable(evaluate_stratified(b.observe(0),cards,('Random',)*3,2,3,10))
