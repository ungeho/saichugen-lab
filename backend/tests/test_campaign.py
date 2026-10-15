from copy import deepcopy
import ast,inspect,subprocess
import pytest
from strategy_arena.experiments.campaign_analysis import CampaignCriteria,campaign_positions,campaign_summary,grouped_deals,interval,METRICS
from strategy_arena.experiments.evolution import digest
from strategy_arena.experiments.noise_lab import StudyConfig,StudyJobs,study_estimate
from strategy_arena.experiments.multideal_analysis import analyze_multideal
from strategy_arena.experiments.adaptive_analysis import select,stopping,draw,sample_table
from strategy_arena.experiments.evidence_lab import EvidenceLab
from test_budget_calibration import config
from test_calibration_coverage import fitted
from test_design_lab import setup
from test_middle_lab import position,wait


@pytest.fixture
def campaign_config(monkeypatch):
    import strategy_arena.experiments.noise_lab as module
    m=fitted();monkeypatch.setattr(module,'FROZEN_MODEL_HASH',digest(m.model_dump(mode='json')))
    return lambda **kw:config(revision='phase41',calibration=m,campaign_periods=['final_round'],**kw)


@pytest.fixture(scope='module')
def evidence():
    state=position(14);obs=state.observe(0);a=analyze_multideal(obs,config(), 'campaign-fixture',0)
    return {'position_hash':'p','deal_hash':'d','deal_id':'41000','turn':14,'period':'final_round',
        'source':'Random','stratum':{'class':'highest'},'game_scores':list(obs.game_scores),'adaptive':a}


def test_core_unchanged_from_phase40():
    old=ast.parse(subprocess.check_output(['git','show','3cfead4:backend/src/strategy_arena/experiments/adaptive_analysis.py']).decode())
    for f in (select,stopping,draw,sample_table):
        assert ast.dump(next(x for x in old.body if isinstance(x,ast.FunctionDef) and x.name==f.__name__))==ast.dump(ast.parse(inspect.getsource(f)).body[0])


def test_schedule_unique_deals_deterministic_and_missing_fails():
    records=[{'deal_hash':d,'position_hash':d+p,'period':p,'source':'Random','stratum':{'class':'tie'}} for d in ('a','b','c') for p in ('early','final_round')]
    result=campaign_positions(records,['early','final_round','final_round'])
    assert len({p['deal_hash'] for p in result})==3 and result==campaign_positions(list(reversed(records)),['early','final_round','final_round'])
    with pytest.raises(ValueError):campaign_positions(records,['middle'])


def test_frozen_model_hash_and_schedule_config(campaign_config):
    c=campaign_config();f=study_estimate(c)['completion_forecast'];assert f['model_hash']==digest(c.calibration.model_dump(mode='json'))
    assert len(f['slots'])==1 and f['slots'][0]['period']=='final_round'
    assert f==study_estimate(c)['completion_forecast']
    with pytest.raises(ValueError):StudyConfig(**{**c.model_dump(),'campaign_periods':[]})
    bad=c.model_dump();bad['calibration']['safety_factor']=2
    with pytest.raises(ValueError):StudyConfig(**bad)
    with pytest.raises(ValueError):config(campaign_periods=['final_round'])


def test_custom_assignment_changes_only_pre_run_slot_counts(campaign_config):
    c=campaign_config();c=c.model_copy(update={'deals':5,'max_positions':5,'turns':[4,10,11,14],'campaign_periods':['early','middle','before_final_round','final_round','final_round'],'max_derived_games':80000})
    v=study_estimate(c)
    assert v['derived_games_upper']==(13+7+6+3+3)*544*3
    assert [s['period'] for s in v['completion_forecast']['slots']]==c.campaign_periods


def test_hierarchical_equal_weight_not_decision_count():
    rows=[]
    for deal,pos,model,values in [('a','p','Random',[0,0]),('a','p','Heuristic',[2]),('a','q','Random',[3]),('b','r','Random',[10])]:
        rows.extend({'deal_hash':deal,'position_hash':pos,'model':model,**{k:v for k in METRICS}} for v in values)
    ds=grouped_deals(rows);assert [d['reward_difference'] for d in ds]==[2,10]


def test_five_categories_and_negative_regret_preserved(evidence):
    ps=[]
    for index,(div,early,reward) in enumerate([(False,False,0),(False,True,0),(True,True,.5),(True,True,-.5),(True,True,0)]):
        p=deepcopy(evidence);p.update(position_hash=str(index),deal_hash=str(index))
        r=next(r for r in p['adaptive']['rows'] if r['model']=='Random' and r['method']=='Gap-Adaptive')
        fixed=next(x for x in p['adaptive']['rows'] if x['model']=='Random' and x['method']=='Fixed')
        other=next(x['card'] for x in r['candidates'] if x['card']!=fixed['selected_card'])
        r['selected_card']=other if div else fixed['selected_card'];r['early_stop']=early;r['evaluations'][0]['minus_fixed']['mean']=reward;r['evaluations'][0]['estimated_regret']['mean']=-.25
        ps.append(p)
    result=campaign_summary(ps,CampaignCriteria(),complete=True)
    gap=next(x for x in result['secondary_exploratory'] if x['method']=='Gap-Adaptive' and x['stratum']=='model' and x['value']=='Random')
    assert set(gap['categories'])=={'same_full_budget','same_early_stop','divergent_positive','divergent_negative','divergent_zero'}
    assert gap['metrics']['estimated_regret']['mean']==-.25 and gap['divergent_deals']==3 and gap['decisions']==5
    assert gap['adoption']=='現時点では採用根拠不足'


def test_no_divergence_still_in_primary_and_partial_hidden(evidence):
    a=campaign_summary([evidence],CampaignCriteria(),complete=True)
    assert len(a['primary'])==3 and all(r['independent_deals']==1 for r in a['primary'])
    b=campaign_summary([evidence],CampaignCriteria(),complete=False)
    assert b['primary'] is None and b['secondary_exploratory'] is None and len(b['partial_evidence'])==9


def test_bootstrap_is_deterministic_and_small_sample_safe():
    c=CampaignCriteria();assert interval([1],c,'same') is None
    assert interval([0,0],c,'same')==[0,0]
    assert interval([-1,0,1],c,'same')==interval([-1,0,1],c,'same')
    with pytest.raises(ValueError):CampaignCriteria(minimum_deals=2)


def test_evidence_actual_scores_and_seed_strings_no_hidden_hands(evidence):
    p=deepcopy(evidence);before=deepcopy(p);v=campaign_summary([p],CampaignCriteria(),complete=True)
    assert p==before
    for r in v['partial_evidence']:
        assert r['score_change'] is None and '未保存' in r['score_change_note']
        assert all(isinstance(x,str) for x in r['stage_seeds'].values())
        assert not any(k in r for k in ('hands','unused_card','actual_opponent_hands'))
        assert r['wall_difference']==pytest.approx(r['wall_seconds']-next(x['wall_seconds'] for x in v['partial_evidence'] if x['model']==r['model'] and x['method']=='Fixed'))


def test_campaign_sqlite_plan_gate_and_cancel(tmp_path,campaign_config):
    design,ev,arena=setup(tmp_path);lab=StudyJobs(design.store,design,EvidenceLab(design.store,design))
    try:
        old=design.store.save({'kind':'old','status':'TimedOut','seed':'18446744073709551615'})
        c=campaign_config();from strategy_arena.experiments.runtime_analysis import environment
        e=environment(c);c.calibration.environment={k:e[k] for k in ('os','cpu','python')}
        import strategy_arena.experiments.noise_lab as module
        original=module.FROZEN_MODEL_HASH;module.FROZEN_MODEL_HASH=digest(c.calibration.model_dump(mode='json'))
        try:
            v=lab.register(c);snap=deepcopy(v['snapshot']);assert v['campaign_evidence']['primary'] is None
            lab.start(v['id'],v['condition_hash']);v=wait(lab,v['id']);assert v['status']=='Completed',v.get('error')
            assert v['campaign_evidence']['primary_finalized'] and v['snapshot']==snap
            assert lab.get(v['id'])['campaign_evidence']==v['campaign_evidence']
            assert design.store.get(old)['seed']=='18446744073709551615'
            cancelled=lab.register(c.model_copy(update={'start_offset':41001}));lab.start(cancelled['id'],cancelled['condition_hash']);lab.cancel(cancelled['id']);cancelled=wait(lab,cancelled['id'])
            assert cancelled['status']=='Cancelled' and cancelled['campaign_evidence']['primary'] is None
        finally:module.FROZEN_MODEL_HASH=original
    finally:lab.close();design.close();ev.close();arena.close()
