import ast,inspect,json,subprocess
from collections import Counter
from copy import deepcopy
import pytest
from strategy_arena.experiments.noise_lab import StudyConfig,StudyJobs,study_estimate
from strategy_arena.experiments.lightweight_analysis import analyze_lightweight,lightweight_summary,coverage_summary,balanced_order
from strategy_arena.experiments.noise_analysis import analyze_divergence
from strategy_arena.experiments.adaptive_analysis import select,stopping
from strategy_arena.experiments.evidence_lab import EvidenceLab
from test_design_lab import setup
from test_middle_lab import position,wait

def config(**kw):return StudyConfig(**{'revision':'phase37','turns':[14],'max_positions':1,'deals':1,'measurement_repeats':6,**kw})

def test_select_and_stopping_identical_to_phase36():
    old=subprocess.check_output(['git','show','c20e0e33d632115f74a570f3b7cc07c764c7b95b:backend/src/strategy_arena/experiments/adaptive_analysis.py']).decode()
    for f in (select,stopping):assert ast.dump(next(n for n in ast.parse(old).body if isinstance(n,ast.FunctionDef) and n.name==f.__name__))==ast.dump(ast.parse(inspect.getsource(f)).body[0])

@pytest.mark.parametrize('modes',[['Baseline','Lightweight'],['Baseline','Lightweight','Detailed Profile']])
def test_balanced_each_condition_visits_every_order_position(modes):
    c=config(measurement_modes=modes,measurement_repeats=3*len(modes));orders=[balanced_order(c,'p','Random',i,32,'measurement') for i in range(c.measurement_repeats)]
    assert orders==[balanced_order(c,'p','Random',i,32,'measurement') for i in range(c.measurement_repeats)]
    for condition in orders[0]:assert Counter(order.index(condition) for order in orders)==Counter(range(3*len(modes)))


def test_lightweight_same_result_cost_paired_stats_and_seed():
    g=position(14);before=deepcopy(g.__dict__);c=config();a=analyze_lightweight(g.observe(0),c,'lw')
    assert g.__dict__==before
    rs=a['noise_records'];assert len(rs)==42 and len({r['seed'] for r in rs})==1
    assert all(r['baseline_same_cost'] and r['baseline_same_result'] for r in rs)
    assert all(r['stop_check_seconds'] is None for r in rs)
    assert all(r['lightweight_checkpoints']==r['stop_check_count'] for r in rs if r['mode']=='Lightweight')
    p={'position_hash':'p','deal_hash':'d','adaptive':a};summary=lightweight_summary([p]);assert len(summary)==6
    assert all(s['wall']['n']==6 and s['independent_deals']==1 for s in summary)
    assert all(s['baseline_difference']['mean']==0 for s in summary if s['mode']=='Baseline')
    assert all(isinstance(r['seed'],str) for r in rs)


def test_d_per_deal_events_denominator_sources_and_miss_scenarios():
    c=config(series='D',warmups=0,repeats=1);a=analyze_divergence(position(14).observe(0),c,'d')
    p={'position_hash':'p','deal_hash':'d1','source':'Random','turn':14,'period':'final_round','stratum':{'class':'tie'},'adaptive':a}
    summary=coverage_summary([p,{**p,'deal_hash':'d2','position_hash':'p2'}])
    r=next(r for r in summary if r['stratum']=='all' and r['method']=='Gap-Adaptive')
    assert r['independent_deals']==2 and r['positions']==2 and r['raw_decisions']==2
    assert len(r['deal_events'])==2 and r['event_interval'] is None
    if r['deal_event_count']==0:assert r['miss_scenarios'][0]['zero_events_probability']==pytest.approx(.9**2)
    assert any(r['stratum']=='source:Random' for r in summary)

@pytest.mark.parametrize('kw',[{'measurement_modes':['Baseline','Baseline']},{'measurement_modes':['Lightweight','Detailed Profile']},
 {'measurement_repeats':3},{'measure_stopping':True},{'series':'D','warmups':0,'deals':2,'max_positions':3},
 {'series':'D','warmups':0,'stage':'independent_validation','partition':'validation','start_offset':1930000,'budgets':[128]}])
def test_new_limits_and_coverage(kw):
    with pytest.raises(ValueError):config(**kw)


def test_old_rows_unchanged_and_new_plan_saved(tmp_path):
    design,ev,arena=setup(tmp_path);lab=StudyJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        old=lab.register(StudyConfig(turns=[14],max_positions=1,start_offset=38100));lab.start(old['id'],old['condition_hash']);old=wait(lab,old['id']);assert old['status']=='Completed'
        oldraw=design.store.get(old['id']);v=lab.register(config(start_offset=38200));assert v['snapshot']['study_plan']['version']=='runtime-divergence-phase37-v1'
        assert v['snapshot']['study_plan']['primary_comparisons']==['Lightweight - Baseline']
        lab.start(v['id'],v['condition_hash']);v=wait(lab,v['id']);assert v['status']=='Completed',v.get('error')
        assert design.store.get(old['id'])==oldraw and lab.get(old['id'])['condition_hash']==old['condition_hash']
        assert all(x['same_cost'] and x['same_result'] for x in v['cluster_summary'])
        assert json.loads(json.dumps(v))['positions']==v['positions']
    finally:lab.close();design.close();ev.close();arena.close()

def test_lightweight_cancel_keeps_partial_measurement(tmp_path,monkeypatch):
    import strategy_arena.experiments.lightweight_analysis as mod
    from threading import Event
    gate=Event();entered=Event();real=mod.select;calls=[0]
    def pause(*a,**kw):
        calls[0]+=1
        if calls[0]==2:entered.set();gate.wait(5)
        return real(*a,**kw)
    monkeypatch.setattr(mod,'select',pause)
    design,ev,arena=setup(tmp_path);lab=StudyJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        v=lab.register(config(start_offset=38300));lab.start(v['id'],v['condition_hash']);assert entered.wait(5)
        lab.cancel(v['id']);gate.set();v=wait(lab,v['id']);assert v['status']=='Cancelled' and v['cluster_summary'] is None
        assert v['runtime_measurements'][0]['wall_seconds'] is None
    finally:gate.set();lab.close();design.close();ev.close();arena.close()
