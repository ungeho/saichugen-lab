from copy import deepcopy
from dataclasses import asdict
import json,sqlite3
import pytest
from fastapi.testclient import TestClient
from strategy_arena.api.app import create_app
from strategy_arena.experiments.decision_analysis import safety_margin,enrich_candidate,choose_rules,evaluate_rules,decision_positions,decision_summary,paired_reward,RULES
from strategy_arena.experiments.decision_lab import DecisionConfig,DecisionJobs,decision_estimate
from strategy_arena.experiments.stratification_lab import StratificationJobs,StratificationConfig,collect
from strategy_arena.experiments.evidence_lab import EvidenceLab,SeriesSpec
from strategy_arena.game.engine import Game
from strategy_arena.game.cards import deal
from test_design_lab import setup
from test_middle_lab import position,wait


def test_safety_margin_and_non_middle():
    assert safety_margin((1,5,9),1)=={'strict_middle':True,'minimum_margin':4,'signed_minimum_margin':4,'margin_balance':0,'upper_gap':4,'lower_gap':4}
    assert safety_margin((1,8,10),1)['margin_balance']==5
    for scores,p in [((1,1,9),1),((1,5,9),0),((1,5,9),2),((1,1,1),1)]:
        v=safety_margin(scores,p);assert v['minimum_margin'] is None and v['signed_minimum_margin']<=0


def test_candidate_margin_is_conditional_not_positive_outside_middle():
    v=enrich_candidate({'next_scores_distribution':{'0,4,10':2,'0,12,10':2}},1)
    assert v['minimum_margin_if_middle']==4 and v['middle_worlds']==2
    assert v['signed_minimum_margin_mean']==1 and v['next_opponent_gap']==10
    assert enrich_candidate({'next_scores_distribution':{'0,12,10':2}},1)['minimum_margin_if_middle'] is None


def candidates():
    return [{'card':{'rank':i+1,'suit':0},'immediate_middle':a,'next_opponent_gap':g,'next_strict_middle':s,'minimum_margin_if_middle':m,'reward':r} for i,(a,g,s,m,r) in enumerate([(.9,1,.4,1,0),(.1,10,.2,2,-.5),(.2,3,.8,5,.2),(.1,1,.3,2,1)])]


def test_four_objectives_and_fixed_tie_break():
    rows=candidates();chosen=choose_rules(rows)
    assert [chosen[r]['rank'] for r in RULES]==[1,2,3,4]
    assert chosen==choose_rules(list(reversed(rows)))
    duplicate={**rows[0],'card':{'rank':1,'suit':1}}
    assert choose_rules([duplicate,rows[0]])['Self-Middle']==rows[0]['card']


def test_safety_priority_tolerance_and_no_middle_samples():
    rows=candidates();rows[3].update(next_strict_middle=.79,minimum_margin_if_middle=20)
    assert choose_rules(rows)['Safety-Margin']['rank']==3
    assert choose_rules(rows,.02)['Safety-Margin']['rank']==4
    for c in rows:c.update(next_strict_middle=0,minimum_margin_if_middle=None)
    assert choose_rules(rows)['Safety-Margin']['rank']==1
    with pytest.raises(ValueError):choose_rules(rows,float('nan'))


def stable(v):
    if isinstance(v,(list,tuple)):return [stable(x) for x in v]
    if isinstance(v,dict):return {k:stable(x) for k,x in v.items() if k not in ('rollout_seconds','selection_seconds','evaluation_seconds')}
    return v


def test_independent_fixed_choice_seed_reproducibility_and_reward_pairs():
    g=position(12);o=g.observe(0);before=deepcopy(g.__dict__);c=DecisionConfig(trials=2,evaluation_trials=10)
    selection,d=evaluate_rules(o,c,'fixed-position')
    assert stable([selection,d])==stable(evaluate_rules(o,c,'fixed-position'))
    assert selection['seed']!=d['evaluation']['seed']
    assert len(selection['candidates'])==len(o.legal_actions)
    assert len(d['evaluation']['candidates'])==d['unique_selected_cards']<=4
    assert all(r['selected_card'] in [asdict(card) for card in o.legal_actions] for r in d['rules'])
    for pair in d['comparisons']:
        left=next(r['evaluation']['reward'] for r in d['rules'] if r['rule']==pair['left'])
        right=next(r['evaluation']['reward'] for r in d['rules'] if r['rule']==pair['right'])
        assert pair['reward_difference']['mean']==pytest.approx(left-right)
        assert pair['reward_difference']['independent_world_samples']==10
    assert g.__dict__==before
    _,other=evaluate_rules(o,c.model_copy(update={'validation_offset':11111}),'fixed-position')
    assert [r['selected_card'] for r in d['rules']]==[r['selected_card'] for r in other['rules']]


def test_same_card_comparison_is_exact_zero():
    card={'rank':1,'suit':0}
    p=paired_reward({'candidates':[{'trials':10}]},card,card)
    assert p['mean']==0 and p['interval']==[0,0]


def test_actual_hidden_cards_not_used():
    hands,unused=deal(42);g=Game.from_deal(hands,unused);other=Game.from_deal((hands[0],hands[2],hands[1]),unused)
    assert g.observe(0)==other.observe(0)
    c=DecisionConfig(trials=2,evaluation_trials=10)
    assert stable(evaluate_rules(g.observe(0),c,'same'))==stable(evaluate_rules(other.observe(0),c,'same'))


def test_collection_selection_coverage_and_order():
    rows,_,_=collect(DecisionConfig(deals=4,start_offset=11000))
    selected=decision_positions(rows,12,3)
    assert selected==decision_positions(list(reversed(rows)),12,3)
    assert len({p['position_hash'] for p in selected})==len(selected)
    for label in ('both_small','both_large'):
        if any(r['stratum'][label] for r in rows):assert any(r['stratum'][label] for r in selected)
    assert set(p['stratum']['class'] for p in selected if not p['stratum']['strict_middle'])=={'highest','lowest','tie'}


def test_limits_and_partitions():
    for kw in ({'start_offset':2000000},{'evaluation_trials':129},{'safety_tolerance':.2},{'max_validate':1},{'continuation':('monte_carlo_rollout',)*3},{'max_positions':24,'evaluation_trials':128}):
        with pytest.raises(ValueError):DecisionConfig(**kw)
    assert decision_estimate(DecisionConfig())['derived_games_upper']==3168


def test_cluster_averages_deals_not_positions():
    def row(deal,diff):
        return {'deal_hash':deal,'stratum':{'class':'strict_middle','strict_middle':True,'relation':'balanced','both_small':True,'both_large':False},'period':'middle','source':'Random',
            'decision':{'all_agree':False,'self_terminal_disagree':True,
            'comparisons':[{'left':a,'right':b,'reward_difference':{'mean':diff}} for a,b in (('Safety-Margin','Self-Middle'),('Gap-Control','Self-Middle'),('Terminal-Value','Self-Middle'),('Safety-Margin','Gap-Control'))],
            'agreement_pairs':[{'left':a,'right':b,'same_card':False} for i,a in enumerate(RULES) for b in RULES[i+1:]]}}
    group=next(g for g in decision_summary([row('a',1),row('a',3),row('b',1)]) if g['stratum']=='all')
    assert group['independent_deals']==2 and group['positions']==3
    assert group['comparisons'][0]['evidence']['mean']==1.5
    # Existing fixed-sample helper deliberately withholds an interval below 10 deals.
    assert group['comparisons'][0]['evidence']['interval'] is None


def test_storage_previous_rows_hash_links_and_deal_units(tmp_path):
    design,ev,arena=setup(tmp_path);evidence=EvidenceLab(design.store,design);old=StratificationJobs(design.store,design,evidence);lab=DecisionJobs(design.store,design,evidence)
    try:
        previous=old.register(StratificationConfig(deals=1,turns=[14],start_offset=35000,validation_offset=35000));baseline=deepcopy(design.store.get(previous['id']))
        v=lab.register(DecisionConfig(deals=1,turns=[12],max_positions=3,controls=0,trials=2,evaluation_trials=10,start_offset=36000,validation_offset=36000))
        with pytest.raises(ValueError):lab.register(DecisionConfig(deals=1,start_offset=36000,validation_offset=36000))
        with pytest.raises(ValueError):lab.start(v['id'],'0'*64)
        lab.start(v['id'],v['condition_hash']);v=wait(lab,v['id']);assert v['status']=='Completed',v.get('error')
        assert v==lab.get(v['id']) and v['positions']
        allgroup=next(g for g in v['cluster_summary'] if g['stratum']=='all')
        assert allgroup['independent_deals']==1 and allgroup['positions']==len(v['positions'])
        assert allgroup['comparisons'][0]['evidence']['independent_deals']==1
        assert 'independent_world_samples' not in allgroup['comparisons'][0]['evidence']
        assert design.store.get(previous['id'])==baseline
        assert lab.design_draft(v['id'])['state']=='Draft'
        evidence.create(SeriesSpec(series_id='decision-ref',hypothesis='参照のみ'))
        assert lab.link_evidence(v['id'],'decision-ref',1)['aggregated'] is False
        assert evidence.get('decision-ref',1)['independent_deals']==0
        raw=design.store.get(v['id']);raw['positions'][0]['decision']['all_agree']='tampered'
        with sqlite3.connect(design.store.path) as db:db.execute('UPDATE experiments SET payload=? WHERE id=?',(json.dumps(raw),v['id']))
        assert lab.get(v['id'])['status']=='Invalidated'
    finally:lab.close();old.close();design.close();ev.close();arena.close()


def test_api_estimate_export_cancel_and_reject(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite')) as client:
        config={'deals':1,'turns':[12],'max_positions':2,'controls':0,'trials':2,'evaluation_trials':10}
        assert client.post('/api/decision/estimate',json=config).json()['evaluation_games_upper']==80
        v=client.post('/api/decision/jobs',json=config).json();assert v['status']=='Registered'
        assert client.get('/api/decision/jobs/'+v['id']+'/export').json()==v
        assert client.get('/api/stratification/jobs/'+v['id']).status_code==404
        assert client.post('/api/decision/jobs/'+v['id']+'/cancel',json={}).json()['status']=='Cancelled'
        assert client.post('/api/decision/jobs',json={**config,'expression':'arbitrary code'}).status_code==422


def test_cancel_running_not_completed(tmp_path):
    design,ev,arena=setup(tmp_path);lab=DecisionJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        v=lab.register(DecisionConfig(deals=2,turns=[0,3,6],trials=64,max_positions=2,controls=0,start_offset=37000))
        lab.start(v['id'],v['condition_hash']);lab.cancel(v['id']);assert wait(lab,v['id'])['status']=='Cancelled'
    finally:lab.close();design.close();ev.close();arena.close()
