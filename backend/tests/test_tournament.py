import json,time
from copy import deepcopy
from random import Random
import pytest
from pydantic import ValidationError
from strategy_arena.experiments import tournament as t
from strategy_arena.experiments.storage import ExperimentStore
from strategy_arena.experiments.adaptive_analysis import execution_meter
from strategy_arena.game.engine import Game
from strategy_arena.game.rewards import terminal_rewards

def row(seed,item,winners=(0,)):
    return {'deal_id':seed,**item,'scores':[5,10,20],'winners':list(winners),'terminal_rewards':list(terminal_rewards(winners)),
            'wall_seconds':.1,'decision_samples':[[{'turn':i,'rank':2,'suit':0,'decision_ns':1000,'derived_games':0,'simulated_turns':0} for i in range(15)] for _ in range(3)]}

def wait(lab,id):
    for _ in range(500):
        v=lab.get(id)
        if v['status']!='Running':return v
        time.sleep(.01)
    raise AssertionError('worker did not finish')

def test_schedule_symmetry_and_rotations():
    assert len(t.compositions())==20 and len(t.schedule())==64
    for mode in ('all','symmetric_reduced'):
        rs=t.schedule(mode)
        assert len({tuple(r['assignment']) for r in rs})==len(rs)
        assert len({sum(r['assignment'].count(n) for r in rs) for n in t.PARTICIPANTS})==1
        for c in t.compositions(mode):assert {tuple(r['assignment']) for r in rs if r['composition']==list(c)}==set(__import__('itertools').permutations(c))

def test_limits_uint64_and_partition():
    assert t.TournamentConfig(policy_seed=str(2**64-1)).policy_seed==str(2**64-1)
    for kwargs in ({'policy_seed':2**63},{'policy_seed':str(2**64)},{'deal_seeds':['01']},{'deal_seeds':['1','1']},
                   {'timeout_seconds':901},{'partition':'validation'},{'deal_seeds':['1000000']},{'tournament_version':44}):
        with pytest.raises(ValidationError):t.TournamentConfig(**kwargs)

@pytest.mark.parametrize('winners',[(0,),(1,2),(0,1,2)])
def test_rewards_cluster_and_partial(winners):
    c=t.TournamentConfig(deal_seeds=['45001','45002']);rows=[row(s,r,winners) for s in c.deal_seeds for r in t.schedule()]
    v=t.summary(c,rows,True)
    assert v['complete_deals']==2 and v['primary_finalized']
    assert all(r['independent_deals']==2 and r['seat_appearances']==96 for r in v['ranking'])
    assert all(sum(r['terminal_rewards'])==0 for r in rows)
    assert all(abs(r['mean_reward'])<1e-12 for r in v['ranking']) # all seats symmetric
    assert all(abs(sum(r[k] for k in ('sole_win_rate','two_way_win_rate','three_way_win_rate','loss_rate'))-1)<1e-12 for r in v['ranking'])
    assert t.summary(c,rows[:-1],True)['ranking'] is None
    assert t.summary(c,rows,False)['ranking'] is None
    assert not t.summary(c,rows+[rows[0]],True)['primary_finalized']

def test_real_play_reproducible_and_information(monkeypatch):
    seen=[];factory=t.create_strategy
    class Spy:
        name='Random';version='1'
        def choose(self,obs,rng):
            assert not hasattr(obs,'hands') and not hasattr(obs,'unused') and not hasattr(obs,'seed')
            assert len(obs.hand)==17-obs.turn
            seen.append(obs);return factory('Random').choose(obs,rng)
    monkeypatch.setattr(t,'create_strategy',lambda n:Spy())
    c=t.TournamentConfig();item={'composition':['Random']*3,'assignment':['Random']*3,'rotation':0}
    a=t.play(c,'45003',item);b=t.play(c,'45003',item)
    assert a['scores']==b['scores'] and a['winners']==b['winners']
    assert [[(d['rank'],d['suit']) for d in ds] for ds in a['decision_samples']]==[[(d['rank'],d['suit']) for d in ds] for ds in b['decision_samples']]
    assert len(seen)==90

def test_budget_before_search():
    meter={'limit':1,'policy':{'started_games':0,'completed_games':0,'completed_simulated_turns':0}}
    token=execution_meter.set(meter)
    try:
        with pytest.raises(InterruptedError,match='BudgetExceeded'):t.Measured('hybrid_combined',lambda:None).choose(Game(1).observe(0),Random(2))
        assert meter['policy']['started_games']==0
    finally:execution_meter.reset(token)

def test_registration_hash_old_data_cancel_export(tmp_path):
    store=ExperimentStore(tmp_path/'test.sqlite');old=store.save({'old':'unchanged'});lab=t.TournamentJobs(store,None,None)
    c=t.TournamentConfig(deal_seeds=['45004']);a=lab.register(c);b=lab.register(t.TournamentConfig(deal_seeds=['45005']))
    assert a['snapshot']['study_plan_hash']==t.digest(a['snapshot']['study_plan'])
    assert json.loads(json.dumps(a))['config']['policy_seed']==c.policy_seed
    with pytest.raises(ValueError):lab.register(c)
    assert lab.cancel(a['id'])['status']=='Cancelled'
    assert store.get(old)=={'old':'unchanged'} and lab.get(b['id'])['status']=='Registered'
    lab.close()

@pytest.mark.parametrize('failure',[None,'TimedOut','Cancelled'])
def test_worker_complete_or_partial_and_readback(tmp_path,monkeypatch,failure):
    store=ExperimentStore(tmp_path/'test.sqlite');lab=t.TournamentJobs(store,None,None);calls=[]
    def fake(c,s,item,check):
        calls.append(1)
        if failure and len(calls)==3:
            e=InterruptedError(failure);e.tournament_partial={'deal_id':s};raise e
        return row(s,item)
    monkeypatch.setattr(t,'play',fake);v=lab.register(t.TournamentConfig(deal_seeds=['45006']));lab.start(v['id'],v['condition_hash']);v=wait(lab,v['id'])
    assert v['status']==(failure or 'Completed')
    assert v['tournament_evidence']['primary_finalized']==(failure is None)
    assert t.digest(lab.result_content(store.get(v['id'])))==v['result_hash']
    assert (len(v['partial_games'])==1)==bool(failure)
    other=t.TournamentJobs(store,None,None);assert other.get(v['id'])['tournament_evidence']==v['tournament_evidence'];other.close();lab.close()

def test_used_hash_rejected(tmp_path):
    lab=t.TournamentJobs(ExperimentStore(tmp_path/'test.sqlite'),None,None)
    h=t.deal_identity(45007,t.runtime_info()['source_sha256'])
    with pytest.raises(ValueError,match='Hash'):lab.register(t.TournamentConfig(deal_seeds=['45007'],prior_deal_hashes=[h]))
    lab.close()
