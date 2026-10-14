from copy import deepcopy
from dataclasses import asdict
import json,sqlite3
from random import Random
import pytest
from fastapi.testclient import TestClient
from strategy_arena.api.app import create_app
from strategy_arena.experiments.adaptive_lab import AdaptiveConfig,AdaptiveJobs,adaptive_estimate
from strategy_arena.experiments.adaptive_analysis import select,analyze_adaptive,adaptive_summary,stopping,METHODS
from strategy_arena.experiments.evidence_lab import EvidenceLab
from strategy_arena.experiments.runner import derived_seed
from strategy_arena.game.engine import Game
from strategy_arena.game.cards import deal,Card
from strategy_arena.rollouts import sampled_game
from test_design_lab import setup
from test_middle_lab import position,wait

def config(**kw):return AdaptiveConfig(**{'max_positions':1,'budgets':[16,32],'models':['Random'],'repeats':2,'reference_worlds':16,'final_worlds':16,**kw})
def stable(v):
    if isinstance(v,list):return [stable(x) for x in v]
    if isinstance(v,dict):return {k:stable(x) for k,x in v.items() if not k.endswith('_seconds')}
    return v

def test_fixed_nested_reproducible_order_cost_and_legal():
    g=position(14);o=g.observe(0);before=deepcopy(g.__dict__);c=config();cards=o.legal_actions
    a=select(o,cards,'Random',42,32,'Fixed',c);b=select(o,tuple(reversed(cards)),'Random',42,32,'Fixed',c)
    assert stable(a)==stable(b) and g.__dict__==before
    assert a['trace'][0]['candidates']==select(o,cards,'Random',42,16,'Fixed',c)['candidates']
    assert a['cost']['derived_games']==len(cards)*32 and a['cost']['simulated_turns']==len(cards)*32
    assert Card(**a['selected_card']) in cards and a['stop_reason']=='max_worlds'

def test_stop_rules_are_exploratory_and_not_interval_overlap():
    c=config();certain=[{'gap':1.,'se':0.}]
    assert stopping('Gap-Adaptive',certain,c)=='gap_threshold'
    assert stopping('Uncertainty-Adaptive',certain,c)=='exploratory_paired_se'
    assert stopping('Fixed',certain,c) is None
    assert stopping('Uncertainty-Adaptive',[{'gap':1.,'se':0.},{'gap':.1,'se':1.}],c) is None
    assert stopping('Gap-Adaptive',[{'gap':.5,'se':0.}],c) is None

def test_early_stop_tie_break_and_common_stream(monkeypatch):
    import strategy_arena.experiments.adaptive_analysis as module
    calls=[]
    def fake(obs,cards,model,seed,trial,*_):
        calls.append((seed,trial,tuple(cards)));return [{'reward':2 if i==0 else -1,'immediate_middle':0} for i,_ in enumerate(cards)]
    monkeypatch.setattr(module,'draw',fake);o=position(14).observe(0);c=config()
    rows=[select(o,o.hand,'Random',12,32,m,c) for m in METHODS]
    assert [r['cost']['hidden_worlds'] for r in rows]==[32,16,16]
    assert all(r['selected_card']==asdict(min(o.hand)) for r in rows)
    assert all(seed==12 for seed,_,_ in calls)
    monkeypatch.setattr(module,'draw',lambda obs,cards,*args:[{'reward':0,'immediate_middle':0} for _ in cards])
    r=select(o,o.hand,'Random',12,32,'Uncertainty-Adaptive',c)
    assert r['cost']['hidden_worlds']==32 and r['selected_card']==asdict(min(o.hand))

def test_total_game_cap_no_partial_candidate_blocks():
    o=position(0).observe(0);c=config(budget_mode='total_games',games_per_policy=272)
    r=select(o,o.hand,'Random',1,32,'Fixed',c)
    assert r['cost']['derived_games']==272 and r['cost']['hidden_worlds']==16 and r['stop_reason']=='total_game_cap'
    assert len({r['trials'] for r in r['candidates']})==1

def test_three_independent_stages_negative_regret_and_self_fixed(monkeypatch):
    import strategy_arena.experiments.adaptive_analysis as module
    c=config();pid='negative';ref=derived_seed(1000000+c.validation_offset,f'adaptive-v1:{pid}:reference')
    def fake(obs,cards,model,seed,*_):
        return [{'reward':2 if (i==0 if seed==ref else i==1) else 0,'immediate_middle':int(i==0)} for i,_ in enumerate(cards)]
    monkeypatch.setattr(module,'draw',fake);o=position(14).observe(0);a=analyze_adaptive(o,c,pid)
    assert len(set(a['stage_seeds'].values()))==3
    assert all(e['estimated_regret']['mean']==-2 for r in a['rows'] for e in r['evaluations'])
    assert all(e['minus_self']['mean']==2 for r in a['rows'] for e in r['evaluations'])
    assert stable(a)==stable(analyze_adaptive(o,c,pid))

def test_actual_hidden_hands_not_observed_and_sample_valid():
    hands,unused=deal(42);a=Game.from_deal(hands,unused);b=Game.from_deal((hands[0],hands[2],hands[1]),unused)
    assert a.observe(0)==b.observe(0)
    c=config(budgets=[16]);r=analyze_adaptive(a.observe(0),c,'same')
    assert stable(r)==stable(analyze_adaptive(b.observe(0),c,'same'))
    g=sampled_game(a.observe(0),Random(10));all_cards=[card for p in range(3) for card in g.observe(p).hand]
    assert len(set(all_cards))==51 and g.observe(0)==a.observe(0)

@pytest.mark.parametrize('kw',[{'budgets':[32,16]},{'budgets':[512]},{'initial_worlds':32,'budgets':[16]},
 {'partition':'final'},{'partition':'validation','start_offset':1},{'start_offset':2000000},
 {'gap_threshold':float('nan')},{'models':['Random','Random']},{'max_derived_games':1000,'max_positions':4,'budgets':[256]}])
def test_limits_and_seed_partitions(kw):
    with pytest.raises(ValueError):config(**kw)

def test_summary_independent_deals_not_positions_or_repeats():
    o=position(14).observe(0);a=analyze_adaptive(o,config(),'summary')
    p={'population':'fresh','position_hash':'a','deal_hash':'one','period':'final_round','stratum':{'class':'tie','strict_middle':False},'adaptive':a}
    s=adaptive_summary([p,{**p,'position_hash':'b'},{**p,'population':'diagnostic','position_hash':'c'}])
    assert all(r['independent_deals']==1 and r['deal_evidence']['interval'] is None for r in s)
    assert all(r['positions']==(2 if r['population']=='fresh' else 1) for r in s)

def test_jobs_persistence_cost_hash_cancel_and_old_rows(tmp_path):
    design,ev,arena=setup(tmp_path);lab=AdaptiveJobs(design.store,design,EvidenceLab(design.store,design))
    old=design.store.save({'legacy':'unchanged'});before=design.store.get(old)
    try:
        v=lab.register(config(start_offset=650000,turns=[11]));i=v['id']
        with pytest.raises(ValueError):lab.register(config(start_offset=650000))
        with pytest.raises(ValueError):lab.start(i,'wrong')
        lab.start(i,v['condition_hash']);v=wait(lab,i);assert v['status']=='Completed',v['error']
        costs=v['cost_summary']['total_cost'];meter=v['execution_cost']
        assert costs['derived_games']==sum(meter[s]['completed_games'] for s in ('policy','reference','final'))
        assert costs['simulated_turns']==sum(meter[s]['completed_simulated_turns'] for s in ('policy','reference','final'))
        assert design.store.get(old)==before and v['positions']
        lab2=AdaptiveJobs(design.store,design,EvidenceLab(design.store,design));assert lab2.get(i)['positions']==v['positions'];lab2.close()
        cancelled=lab.register(config(start_offset=650001));assert lab.cancel(cancelled['id'])['status']=='Cancelled'
        assert lab.get(i)['condition_hash']==v['condition_hash'] and json.loads(json.dumps(v))['positions']==v['positions']
    finally:lab.close();design.close();ev.close();arena.close()

def test_api_typed_lookup_export_and_no_run_on_get(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite')) as client:
        assert client.get('/api/adaptive/jobs/missing').status_code==404
        c=config(start_offset=660000).model_dump(mode='json');r=client.post('/api/adaptive/jobs',json=c);assert r.status_code==201,r.text
        j=r.json();assert client.get('/api/adaptive/jobs/'+j['id']+'/export').json()['status']=='Registered'
        assert client.get('/api/reliability/jobs/'+j['id']).status_code==404
        assert client.post('/api/adaptive/jobs/'+j['id']+'/cancel',json={}).json()['status']=='Cancelled'
        assert client.post('/api/adaptive/jobs',json={**c,'partition':'final'}).status_code==422

def test_initial_game_budget_rejected_before_execution():
    with pytest.raises(ValueError):config(turns=[0],budgets=[32],initial_worlds=32,budget_mode='total_games',games_per_policy=272)
    assert config(partition='validation',start_offset=1000000).partition=='validation'

def test_running_cancel_preserves_partial_cost(tmp_path,monkeypatch):
    import time
    import strategy_arena.experiments.adaptive_analysis as module
    real=module.draw
    def slow(*args,**kwargs):time.sleep(.01);return real(*args,**kwargs)
    monkeypatch.setattr(module,'draw',slow)
    design,ev,arena=setup(tmp_path);lab=AdaptiveJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        v=lab.register(config(start_offset=680000,budgets=[64]));lab.start(v['id'],v['condition_hash'])
        for _ in range(100):
            j=lab.get(v['id'])
            if j['execution_cost']['policy']['started_games']>0:break
            time.sleep(.01)
        assert j['status']=='Running' and j['execution_cost']['policy']['started_games']>0
        lab.cancel(v['id']);j=wait(lab,v['id']);assert j['status']=='Cancelled'
        assert j['execution_cost']['policy']['started_games']>=j['execution_cost']['policy']['completed_games']>0
        assert j['cluster_summary'] is None
    finally:lab.close();design.close();ev.close();arena.close()

def test_cross_model_tables_and_single_candidate():
    o=position(14).observe(0);c=config(models=['Random','Heuristic','ScoreAware'],cross_models=True,budgets=[16])
    v=analyze_adaptive(o,c,'cross')
    assert all(len(r['evaluations'])==3 for r in v['rows'])
    single=select(o,o.legal_actions[:1],'Random',1,32,'Gap-Adaptive',c)
    assert single['stop_reason']=='single_legal_action' and Card(**single['selected_card'])==o.legal_actions[0]

def test_check_stops_before_sampling():
    o=position(14).observe(0)
    def stop():raise InterruptedError('Cancelled')
    with pytest.raises(InterruptedError):select(o,o.hand,'Random',1,32,'Fixed',config(),stop)
