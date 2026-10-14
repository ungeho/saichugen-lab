from copy import deepcopy
from dataclasses import asdict
import json,sqlite3
from math import log2
import pytest
from fastapi.testclient import TestClient
from strategy_arena.api.app import create_app
from strategy_arena.experiments.reliability_analysis import nested_selection,distribution,analyze_reliability,reliability_summary
from strategy_arena.experiments.reliability_lab import ReliabilityJobs,ReliabilityConfig,reliability_estimate,restore_observation
from strategy_arena.experiments.decision_lab import DecisionJobs,DecisionConfig
from strategy_arena.experiments.evidence_lab import EvidenceLab,SeriesSpec
from strategy_arena.game.cards import Card,deal
from strategy_arena.game.engine import Game
from test_design_lab import setup
from test_middle_lab import position,wait


def stable(v):
    if isinstance(v,(list,tuple)):return [stable(x) for x in v]
    if isinstance(v,dict):return {k:stable(x) for k,x in v.items() if not k.endswith('_seconds')}
    return v


def test_nested_prefixes_and_fixed_card_tie():
    o=position().observe(0);cards=o.hand[:3]
    rows=nested_selection(o,cards,[16,32],'Random',2,8,100)
    short=nested_selection(o,cards,[16],'Random',2,8,100)
    assert [r['candidates'] for r in rows if r['budget']==16]==[r['candidates'] for r in short]
    reverse=nested_selection(o,tuple(reversed(cards)),[16,32],'Random',2,8,100)
    assert [r['chosen'] for r in rows]==[r['chosen'] for r in reverse]
    assert sum(r['incremental_derived_games'] for r in rows)==len(cards)*32*2
    assert all(r['matches_max_budget'] for r in rows if r['budget']==32)
    assert len({r['seed'] for r in rows})==2


def test_frequency_entropy_and_uncertainty():
    cards=(Card(1,0),Card(2,0));a,b=map(asdict,cards)
    d=distribution(cards,[a,a,b]);assert d['modal_fraction']==pytest.approx(2/3)
    assert d['entropy_bits']==pytest.approx(-(2/3*log2(2/3)+1/3*log2(1/3)))
    assert d['pair_disagreement']==pytest.approx(2/3)
    assert all(f['ci95'][0]<=f['fraction']<=f['ci95'][1] for f in d['frequencies'])
    assert distribution(cards,[a,a])['entropy_bits']==0
    assert distribution(cards,[a])['pair_disagreement'] is None


def small_config(**kwargs):
    return ReliabilityConfig(**{'budgets':[16,32],'models':['Random','Heuristic'],'repeats':2,'evaluation_worlds':16,'max_positions':1,**kwargs})


def test_independent_evaluation_models_optimism_regret_and_counts():
    g=position();o=g.observe(0);before=deepcopy(g.__dict__);c=small_config();v=analyze_reliability(o,c,'fixed')
    assert stable(v)==stable(analyze_reliability(o,c,'fixed'))
    assert g.__dict__==before
    assert v['selection_derived_games']==len(o.hand)*32*2*2
    assert v['evaluation_derived_games']==len(o.hand)*16*2
    for row in v['rows']:
        assert row['seed']!=v['evaluation_tables']['Random']['seed']
        assert all(Card(**card) in o.legal_actions for card in row['chosen'].values())
        for e in row['evaluations']:
            terminal=next(x for x in e['rules'] if x['rule']=='Terminal-Value')
            own=next(x for x in e['rules'] if x['rule']=='Self-Middle')
            assert e['terminal_minus_self']['mean']==pytest.approx(terminal['value']-own['value'])
            assert all(x['estimated_regret']>=0 for x in e['rules'])
            if e['in_model']:
                selected=next(x['reward'] for x in row['candidates'] if x['card']==row['chosen']['Terminal-Value'])
                assert e['selection_optimism']==selected-terminal['value']
            else:assert e['selection_optimism'] is None
    assert all('探索的Regret' in e['regret_method'] for e in v['evaluation_tables'].values())


def test_world_conditions_shared_across_models(monkeypatch):
    import strategy_arena.experiments.reliability_analysis as module
    real=module.rollout_trial;calls=[]
    def wrapped(obs,cards,templates,seed,trial,*args,**kwargs):
        calls.append((kwargs['policy_names'][0],seed,trial,obs))
        return real(obs,cards,templates,seed,trial,*args,**kwargs)
    monkeypatch.setattr(module,'rollout_trial',wrapped)
    obs=position().observe(0);analyze_reliability(obs,small_config(budgets=[16]),'same-worlds')
    a=[(s,t) for m,s,t,_ in calls if m=='Random'];b=[(s,t) for m,s,t,_ in calls if m=='Heuristic']
    assert a==b and all(o is obs for _,_,_,o in calls)


def test_actual_hidden_hands_do_not_affect_reliability():
    hands,unused=deal(42);a=Game.from_deal(hands,unused);b=Game.from_deal((hands[0],hands[2],hands[1]),unused)
    c=small_config(budgets=[16],models=['Random'])
    assert a.observe(0)==b.observe(0)
    assert stable(analyze_reliability(a.observe(0),c,'same'))==stable(analyze_reliability(b.observe(0),c,'same'))


def test_observation_restore_and_limits():
    o=position(11).observe(1);assert restore_observation(asdict(o))==o
    for kw in ({'budgets':[16,16]},{'budgets':[32,16]},{'budgets':[512]},{'repeats':6},{'models':['Random','Random']},{'start_offset':2000000},{'evaluation_worlds':257},{'diagnostic_source_id':'x','max_positions':1}):
        with pytest.raises(ValueError):ReliabilityConfig(**kw)
    assert reliability_estimate(ReliabilityConfig())['derived_games_upper']==20736


def test_population_and_model_summary_not_pooled():
    o=position().observe(0);v=analyze_reliability(o,small_config(budgets=[16]),'summary')
    row={'population':'fresh','deal_hash':'a','position_hash':'p','stratum':{'class':'strict_middle','strict_middle':True,'relation':'balanced','both_small':True,'both_large':False},'period':'final_round_start','reliability':v}
    groups=reliability_summary([row,{**row,'position_hash':'p2'},{**row,'population':'diagnostic','position_hash':'p3'}])
    for g in groups:
        assert g['independent_deals']==1
        assert g['positions']==(2 if g['population']=='fresh' else 1)
        if g['selection_model']!=g['evaluation_model']:assert g['selection_optimism'] is None
        assert g['deal_evidence']['interval'] is None


def test_freeze_historical_source_store_links_and_hash(tmp_path):
    design,ev,arena=setup(tmp_path);evidence=EvidenceLab(design.store,design);decision=DecisionJobs(design.store,design,evidence);lab=ReliabilityJobs(design.store,design,evidence)
    try:
        original=decision.register(DecisionConfig());decision.start(original['id'],original['condition_hash']);source=wait(decision,original['id']);assert source['status']=='Completed'
        before=deepcopy(design.store.get(source['id']))
        c=small_config(budgets=[16],models=['Random'],max_positions=2,diagnostic_source_id=source['id'],start_offset=43000,validation_offset=43000)
        v=lab.register(c);assert len(v['snapshot']['historical'])==1
        assert v['snapshot']['historical'][0]['population']=='diagnostic'
        with pytest.raises(ValueError):lab.register(c)
        with pytest.raises(ValueError):lab.start(v['id'],'x')
        lab.start(v['id'],v['condition_hash']);v=wait(lab,v['id']);assert v['status']=='Completed',v.get('error')
        assert {p['population'] for p in v['positions']}=={'diagnostic','fresh'}
        assert v==lab.get(v['id'])
        assert design.store.get(source['id'])==before
        assert lab.design_draft(v['id'])['state']=='Draft'
        evidence.create(SeriesSpec(series_id='rel-ref',hypothesis='参照のみ'))
        assert lab.link_evidence(v['id'],'rel-ref',1)['aggregated'] is False
        assert evidence.get('rel-ref',1)['independent_deals']==0
        raw=design.store.get(v['id']);raw['positions'][0]['reliability']['legal_count']=99
        with sqlite3.connect(design.store.path) as db:db.execute('UPDATE experiments SET payload=? WHERE id=?',(json.dumps(raw),v['id']))
        assert lab.get(v['id'])['status']=='Invalidated'
    finally:lab.close();decision.close();design.close();ev.close();arena.close()


def test_reject_missing_source_budget_and_cancel(tmp_path):
    design,ev,arena=setup(tmp_path);lab=ReliabilityJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        with pytest.raises(ValueError):lab.register(ReliabilityConfig(diagnostic_source_id='missing'))
        with pytest.raises(ValueError):lab.register(ReliabilityConfig(turns=[0],max_positions=4,repeats=5,evaluation_worlds=256))
        v=lab.register(small_config(start_offset=44000));lab.start(v['id'],v['condition_hash']);lab.cancel(v['id']);assert wait(lab,v['id'])['status']=='Cancelled'
    finally:lab.close();design.close();ev.close();arena.close()


def test_api_export_progress_and_invalid_config(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite')) as client:
        c={'budgets':[16],'models':['Random'],'evaluation_worlds':16,'max_positions':1,'historical_limit':0}
        assert client.post('/api/reliability/estimate',json=c).json()['selection_games_upper']==192
        v=client.post('/api/reliability/jobs',json=c).json();assert v['status']=='Registered'
        assert client.get('/api/reliability/jobs/'+v['id']+'/export').json()==v
        assert client.get('/api/decision/jobs/'+v['id']).status_code==404
        assert client.post('/api/reliability/jobs/'+v['id']+'/cancel',json={}).json()['status']=='Cancelled'
        assert client.post('/api/reliability/jobs',json={**c,'models':['unknown']}).status_code==422
