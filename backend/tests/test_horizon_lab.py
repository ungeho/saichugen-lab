import ast,inspect,json,time
from copy import deepcopy
from dataclasses import asdict
import pytest
from fastapi.testclient import TestClient
from strategy_arena.api.app import create_app
from strategy_arena.experiments.horizon_lab import HorizonConfig,HorizonJobs,horizon_estimate,choose_positions
from strategy_arena.experiments.horizon_analysis import reconstruct,analyze_horizon,horizon_summary
from strategy_arena.experiments.adaptive_analysis import select,stopping,selection_observer,execution_meter
from strategy_arena.experiments.stopping_analysis import rule_fingerprint
from strategy_arena.experiments.evidence_lab import EvidenceLab
from test_design_lab import setup
from test_middle_lab import position,wait
from test_stopping_lab import stable,test_scientific_functions_identical_to_phase32 as baseline_check

def config(**kw):return HorizonConfig(**{'deals':1,'max_positions':1,'turns':[14],'models':['Random'],**kw})

@pytest.mark.parametrize('budget',[16,32,64,128,256])
def test_reconstruction_matches_direct_all_methods_and_nested_prefix(budget):
    o=position(14).observe(0);c=config();path=select(o,o.legal_actions,'Random',8923,256,'Fixed',c);path['repeat']=0
    for method in ('Fixed','Gap-Adaptive','Uncertainty-Adaptive'):
        a=reconstruct(o,path,budget,method,c);b=select(o,tuple(reversed(o.legal_actions)),'Random',8923,budget,method,c)
        for key in ('selected_card','self_middle_card','stop_reason','early_stop','max_budget_reached','candidates'):
            assert a[key]==b[key],(budget,method,key)
        assert a['cost']['elapsed_seconds'] is None
        for key in ('hidden_worlds','derived_games','simulated_turns','simulated_player_actions'):assert a['cost'][key]==b['cost'][key]
        assert [{k:t[k] for k in ('worlds','selected_card','candidates','contrasts','stop_reason')} for t in a['trace']]==[{k:t[k] for k in ('worlds','selected_card','candidates','contrasts','stop_reason')} for t in b['trace']]
        if budget==16:assert not a['early_stop'] and a['max_budget_reached']


def test_frozen_rules_and_observer_no_effect():
    baseline_check()
    o=position(14).observe(0);c=config();a=select(o,o.legal_actions,'Random',7,32,'Fixed',c)
    events=[];token=selection_observer.set(lambda *args:events.append(args))
    try:b=select(o,o.legal_actions,'Random',7,32,'Fixed',c)
    finally:selection_observer.reset(token)
    assert stable(a)==stable(b) and len(events)==4
    assert rule_fingerprint()=='b774337d8b3525d0f254d7dc9611e43403fc8db77d2001b2ff962806e4126fe4'


def test_cap_condition_and_post_stop_changes_are_not_used_to_select():
    o=position(14).observe(0);c=config();p=select(o,o.legal_actions,'Random',11,256,'Fixed',c);p['repeat']=0
    a,b=p['trace'][0]['selected_card'],asdict(next(x for x in o.legal_actions if asdict(x)!=p['trace'][0]['selected_card']))
    for t in p['trace']:t['contrasts']=[{'card':b,'gap':.75,'se':.1}]
    p['trace'][1]['selected_card']=b
    x=reconstruct(o,p,16,'Gap-Adaptive',c);assert x['first_condition_worlds']==16 and not x['early_stop']
    x=reconstruct(o,p,128,'Gap-Adaptive',c);assert x['selected_card']==a and x['actual_stop_worlds']==16
    assert x['post_stop_fixed_changes'][0]['worlds']==32
    p['trace'][-1]['selected_card']=b
    assert reconstruct(o,p,128,'Gap-Adaptive',c)['selected_card']==a


def test_three_streams_reproducibility_costs_and_deal_clusters():
    g=position(14);before=deepcopy(g.__dict__);o=g.observe(0);c=config(budgets=[16,32],policy_seed=91827)
    a=analyze_horizon(o,c,'p');assert stable(a)==stable(analyze_horizon(o,c,'p'))
    assert g.__dict__==before and len(set(a['stage_seeds'].values()))==3
    assert json.loads(json.dumps(a))['stage_seeds']==a['stage_seeds']
    expected=len(o.legal_actions)*(32*c.repeats+c.reference_worlds+c.final_worlds)
    assert a['actual_research_compute_cost']['derived_games']==expected
    assert all(r['counterfactual_policy_cost']['elapsed_seconds'] is None for r in a['rows'])
    p={'position_hash':'p','deal_hash':'d','turn':14,'period':'final_round','stratum':{'class':'tie'},'adaptive':a}
    summary=horizon_summary([p,{**p,'position_hash':'p2'}]);assert all(r['independent_deals']==1 for r in summary)
    assert all(r['reward_difference_evidence']['interval'] is None for r in summary)
    for r in a['rows']:
        e=r['evaluations'][0]
        assert e['estimated_regret']['mean']==pytest.approx(next(x['reward'] for x in a['final']['Random']['candidates'] if x['card']==e['reference_card'])-e['value'])

@pytest.mark.parametrize('kw',[{'start_offset':1900000},{'start_offset':1899999,'deals':2,'max_positions':2},{'gap_threshold':.4},{'batch_worlds':8},{'initial_worlds':32},{'uncertainty_z':3},{'minimum_gap':0},{'budget_mode':'total_games'},{'max_positions':1,'deals':2},{'budgets':[32,16]},{'budgets':[512]},{'turns':[0],'max_positions':8,'deals':4,'models':['Random','Heuristic','ScoreAware']}])
def test_invalid_configuration(kw):
    with pytest.raises(ValueError):config(**kw)


def test_new_estimate_counts_only_maximum_path():
    c=HorizonConfig();e=horizon_estimate(c);assert e['derived_games_upper']==19584
    assert e['selection_games_upper']==2*6*256*2*3


def test_position_selection_prioritizes_independent_deals_and_is_deterministic():
    rows=[{'position_hash':str(i),'deal_hash':str(i//3),'period':'early' if i%2 else 'final_round','stratum':{'class':'tie'},'source':'Random'} for i in range(9)]
    a=choose_positions(rows,3);assert len({r['deal_hash'] for r in a})==3
    assert a==choose_positions(list(reversed(rows)),3)


def test_hash_sqlite_old_rows_cancel_and_namespace(tmp_path):
    design,ev,arena=setup(tmp_path);lab=HorizonJobs(design.store,design,EvidenceLab(design.store,design));old=design.store.save({'old':'unchanged'})
    try:
        v=lab.register(config(start_offset=1970000,budgets=[16,32]));plan=v['snapshot']['horizon_plan']
        assert plan['primary_priority']['budget']==128 and plan['rules_hash']==rule_fingerprint()
        with pytest.raises(ValueError):lab.start(v['id'],'bad')
        lab.start(v['id'],v['condition_hash']);v=wait(lab,v['id']);assert v['status']=='Completed',v.get('error')
        assert v['stopping_trace'] and v['cluster_summary'] and not v['missing_positions']
        assert len(v['planned_positions'])==1 and len(v['coverage'])==20
        assert design.store.get(old)=={'old':'unchanged'}
        other=HorizonJobs(design.store,design,EvidenceLab(design.store,design));assert other.get(v['id'])['positions']==v['positions'];other.close()
        with pytest.raises(ValueError):lab.register(config(start_offset=1970000))
    finally:lab.close();design.close();ev.close();arena.close()
    with TestClient(create_app(tmp_path/'api.sqlite')) as client:
        r=client.post('/api/stopping-horizon/jobs',json=config(start_offset=1971000,budgets=[16,32]).model_dump(mode='json'));assert r.status_code==201,r.text
        v=r.json();assert client.get('/api/stopping/jobs/'+v['id']).status_code==404
        assert client.get('/api/stopping-horizon/jobs/missing').status_code==404
        assert client.get('/api/stopping-horizon/jobs/'+v['id']+'/export').json()['status']=='Registered'
        assert client.post('/api/stopping-horizon/jobs/'+v['id']+'/cancel',json={}).json()['status']=='Cancelled'


def test_running_cancel_preserves_research_checkpoints_and_no_complete_summary(tmp_path,monkeypatch):
    import strategy_arena.experiments.adaptive_analysis as mod
    real=mod.draw
    def slow(*a,**kw):time.sleep(.01);return real(*a,**kw)
    monkeypatch.setattr(mod,'draw',slow)
    design,ev,arena=setup(tmp_path);lab=HorizonJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        v=lab.register(config(start_offset=1972000));lab.start(v['id'],v['condition_hash'])
        for _ in range(300):
            v=lab.get(v['id'])
            if any(s['checkpoints'] for s in v.get('stopping_trace',[])):break
            time.sleep(.01)
        assert any(s['checkpoints'] for s in v['stopping_trace'])
        lab.cancel(v['id']);v=wait(lab,v['id']);assert v['status']=='Cancelled' and v['cluster_summary'] is None
        assert any(s['classification']=='cancelled' for s in v['stopping_trace'])
        assert v['execution_cost']['policy']['completed_games']>0
    finally:lab.close();design.close();ev.close();arena.close()
