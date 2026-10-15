import ast,inspect,json,subprocess
from collections import Counter
from copy import deepcopy
import pytest
from strategy_arena.experiments.noise_lab import StudyConfig,StudyJobs,study_estimate
from strategy_arena.experiments.multideal_analysis import analyze_multideal,multideal_summary,method_order
from strategy_arena.experiments.adaptive_analysis import select,stopping
from strategy_arena.experiments.evidence_lab import EvidenceLab,deal_identity
from strategy_arena.experiments.rollout_quality import runtime_info
from strategy_arena.experiments.evolution import digest
from test_design_lab import setup
from test_middle_lab import position,wait

def config(**kw):
    return StudyConfig(**{'revision':'phase38','series':'D','turns':[14],'deals':1,'max_positions':1,'budgets':[128],
      'repeats':1,'warmups':1,'models':['Random','Heuristic','ScoreAware'],'start_offset':38000,**kw})

def test_phase37_frozen_algorithms():
    old=subprocess.check_output(['git','show','66c71f4:backend/src/strategy_arena/experiments/adaptive_analysis.py']).decode()
    for f in (select,stopping):assert ast.dump(next(n for n in ast.parse(old).body if isinstance(n,ast.FunctionDef) and n.name==f.__name__))==ast.dump(ast.parse(inspect.getsource(f)).body[0])

@pytest.mark.parametrize('kw',[{'budgets':[64]},{'models':['Random']},{'repeats':2},{'series':'R'},{'deals':2,'max_positions':1},{'measure_stopping':True},
 {'stage':'independent_validation','partition':'validation','start_offset':1950000},{'prior_deal_hashes':['x']},{'max_derived_games':1000}])
def test_preregister_limits(kw):
    with pytest.raises(ValueError):config(**kw)

def test_balanced_across_deals_and_finite_estimate():
    c=config(deals=6,max_positions=6,turns=[4,10,11,14],warmups=0,max_derived_games=80000,timeout_seconds=250)
    e=study_estimate(c);assert e['derived_games_upper']==79968 and e['reference_games_upper']==2352
    for model in c.models:
        orders=[method_order(c,model,i) for i in range(6)]
        for m in orders[0]:assert Counter(o.index(m) for o in orders)==Counter({0:2,1:2,2:2})

def test_three_streams_direct_paired_time_reproducibility_and_signed_regret():
    g=position(14);before=deepcopy(g.__dict__);c=config()
    a=analyze_multideal(g.observe(0),c,'test',0);b=analyze_multideal(g.observe(0),c,'test',0)
    assert g.__dict__==before and a['stage_seeds']==b['stage_seeds'] and len(set(a['stage_seeds'].values()))==3
    for r,t in zip(a['rows'],b['rows']):
        assert r['selected_card']==t['selected_card'] and r['evaluations']==t['evaluations']
        m=r['direct_measurement'];assert m['path_matches'] and isinstance(m['seed'],str) and m['mode']=='Lightweight'
        if r['method']=='Fixed':assert m['wall_difference']==0
    assert len(a['noise_records'])==18 and all(x['measurement_completed'] for x in a['noise_records'])
    p={'position_hash':'p','deal_hash':'d','source':'Random','turn':14,'period':'final_round','stratum':{'class':'tie'},'adaptive':a}
    for r in a['rows']:r['evaluations'][0]['estimated_regret']['mean']=-.5
    rows=multideal_summary([p]);s=next(r for r in rows if r['stratum']=='all' and r['method']=='Gap-Adaptive')
    assert s['independent_deals']==1 and len(s['paired_deals'])==1 and s['estimated_regret']==-.5
    primary=[r for r in rows if r['analysis_role']=='primary'];assert len(primary)==2
    assert all(r['independent_deals']==1 and r['reward_difference_interval'] is None for r in primary)
    # 同配札内の局面を複製しても独立数は増えない。
    assert all(r['independent_deals']==1 for r in multideal_summary([p,{**p,'position_hash':'p2'}]))

def test_plan_hash_old_rows_duplicate_and_reload(tmp_path):
    design,ev,arena=setup(tmp_path);lab=StudyJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        old=lab.register(StudyConfig(turns=[14],max_positions=1,start_offset=88000));oldraw=design.store.get(old['id'])
        c=config();v=lab.register(c);snap=deepcopy(v['snapshot']);plan=snap['study_plan']
        assert digest(plan)==snap['study_plan_hash'] and plan['fixed'] and plan['primary_budget']==128
        assert len(plan['primary_comparisons'])==2
        with pytest.raises(ValueError):lab.register(c)
        h=deal_identity(38001,runtime_info()['source_sha256'])
        with pytest.raises(ValueError):lab.register(config(start_offset=38001,prior_deal_hashes=[h]))
        lab.start(v['id'],v['condition_hash']);v=wait(lab,v['id']);assert v['status']=='Completed',v.get('error')
        assert v['snapshot']==snap and design.store.get(old['id'])==oldraw
        assert json.loads(json.dumps(lab.get(v['id'])))['snapshot']==snap
        assert len(v['positions'])==1 and len(v['runtime_measurements'])==18
        assert set(v['positions'][0]['observation']).isdisjoint({'hands','unused','seed'})
    finally:lab.close();design.close();ev.close();arena.close()

def test_tampered_plan_or_config_rejected(tmp_path):
    design,ev,arena=setup(tmp_path);lab=StudyJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        v=lab.register(config());raw=design.store.get(v['id']);raw['config']['deals']=2;design.store.update(v['id'],raw)
        with pytest.raises(ValueError,match='Hash'):lab.start(v['id'],v['condition_hash'])
    finally:lab.close();design.close();ev.close();arena.close()

def test_cancel_retains_partial_timing_without_completed_summary(tmp_path,monkeypatch):
    import strategy_arena.experiments.multideal_analysis as mod
    from threading import Event
    entered=Event();release=Event();real=mod.select
    def pause(*args,**kwargs):
        entered.set();release.wait(5);return real(*args,**kwargs)
    monkeypatch.setattr(mod,'select',pause)
    design,ev,arena=setup(tmp_path);lab=StudyJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        v=lab.register(config());lab.start(v['id'],v['condition_hash']);assert entered.wait(5)
        lab.cancel(v['id']);release.set();v=wait(lab,v['id'])
        assert v['status']=='Cancelled' and v['cluster_summary'] is None
        assert v['runtime_measurements'][0]['wall_seconds'] is None and v['missing_positions']
    finally:release.set();lab.close();design.close();ev.close();arena.close()
