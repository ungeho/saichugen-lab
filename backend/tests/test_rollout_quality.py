from copy import deepcopy
from threading import Event
from time import monotonic, sleep
import json

import pytest
from fastapi.testclient import TestClient

from strategy_arena.api.app import create_app
from strategy_arena.experiments.rollout_quality import (StudyConfig, BASELINE_COMMIT, KIND, estimate,
    run_study, summarize_study, interval, probe, presets)
from strategy_arena.experiments.quality_jobs import QualityJobs
from strategy_arena.experiments.storage import ExperimentStore
from strategy_arena.game.rewards import terminal_rewards
import strategy_arena.experiments.rollout_quality as module
import strategy_arena.experiments.quality_jobs as jobs_module


def config(**kwargs):
    return StudyConfig(settings=[{'trials':1,'continuation':'Random'}, {'trials':2,'continuation':'Random'}],
                       analyze_position=False, **kwargs)


def wait(jobs, identifier):
    deadline=monotonic()+10
    while monotonic()<deadline:
        result=jobs.get(identifier, full=True)
        if result['status'] not in ('running','cancelling'):
            return result
        sleep(.01)
    raise AssertionError('job did not finish')


def test_reproducibility_fair_deals_rotation_and_counts(monkeypatch):
    cfg=config()
    calls=[]
    original=module._play_game
    def recording(seed,names,*args,**kwargs):
        calls.append((seed,tuple(r.getstate() for r in kwargs['rngs'])))
        return original(seed,names,*args,**kwargs)
    monkeypatch.setattr(module,'_play_game',recording)
    first=[];second=[]
    run_study(cfg, first.append);run_study(cfg,second.append)
    assert len(first)==12
    for a,b in zip(first,second):
        assert {k:v for k,v in a.items() if k not in ('decisions','game_elapsed_ns')}=={k:v for k,v in b.items() if k not in ('decisions','game_elapsed_ns')}
        assert [d['executed_rollouts'] for d in a['decisions']]==[d['executed_rollouts'] for d in b['decisions']]
        assert tuple(a['terminal_rewards'])==terminal_rewards(a['winners'])
    for i in range(0,12,2):
        assert calls[i]==calls[i+1]  # 同じdeal・roleのrng状態を設定間で共有
    assert {tuple(r['roles']) for r in first}==set(module.ROTATIONS)
    assert {r['seat'] for r in first}=={0,1,2}
    summary=summarize_study(cfg,first)
    assert [s['independent_deals'] for s in summary['settings']]==[1,1]
    assert all(s['reward_ci95'] is None for s in summary['settings'])
    assert summary['settings'][0]['executed_rollouts']==6*150
    assert summary['settings'][1]['executed_rollouts']==6*150*2


def synthetic(cfg, setting, seed, reward, rotations=6):
    return [{'setting':cfg.settings[setting].identifier,'deal_id':str(seed),'rotation':r,'seat':0,
             'terminal_rewards':[reward,-reward,0],'scores':[10,5,20],'winners':[0],
             'game_elapsed_ns':1000000000,'decisions':[{'elapsed_ns':1000000,'started_rollouts':2,
               'executed_rollouts':2,'accepted_rollouts':2,'timed_out':False}]} for r in range(rotations)]


def test_cluster_ci_paired_difference_and_partial_exclusion():
    cfg=config(deal_seeds=[0,1])
    rows=synthetic(cfg,0,0,-1)+synthetic(cfg,0,1,1)+synthetic(cfg,1,0,0)+synthetic(cfg,1,1,2)
    result=summarize_study(cfg,rows)
    assert result['settings'][0]['average_terminal_reward']==0
    assert result['settings'][0]['reward_ci95']==[-1,1]
    assert result['settings'][0]['independent_deals']==2
    assert result['differences'][0]['difference']==1
    assert result['differences'][0]['ci95']==[1,1]
    assert result['differences'][0]['independent_deals']==2
    partial=summarize_study(cfg,rows[:-1])
    assert partial['settings'][1]['excluded_partial_games']==5
    assert partial['settings'][1]['independent_deals']==1
    assert partial['differences'][0]['ci95'] is None
    assert interval([],1) is None and interval([2],1) is None


@pytest.mark.parametrize('changes', [
    {'deal_seeds':[1,1]}, {'deal_seeds':[True]}, {'deal_seeds':[-1,1]}, {'deal_seeds':[9007199254740992]},
    {'settings':[{'trials':65}]}, {'settings':[{'trials':True}]},
    {'settings':[{'trials':8,'continuation':'monte_carlo_rollout'}]},
    {'settings':[{'trials':8},{'trials':8}]}, {'settings':[{'trials':8,'time_limit_ms':True}]},
    {'opponents':['monte_carlo_rollout','Random']},
    {'baseline_commit':'wrong'}, {'timeout_seconds':301},
    {'settings':[{'trials':64}], 'deal_seeds':list(range(20))},
])
def test_invalid_or_excessive_plan(changes):
    payload=config().model_dump();payload.update(changes)
    with pytest.raises(ValueError):StudyConfig.model_validate(payload)


def test_presets_and_estimate_cover_required_settings():
    plans=presets()
    assert len(plans)==2
    settings=[s for p in plans for s in p['config']['settings']]
    assert {s['trials'] for s in settings}=={8,16,32,64}
    assert {s['continuation'] for s in settings}=={'Random','Greedy','ScoreAware'}
    assert estimate(config())['games']==12


def test_probe_only_saves_own_observation():
    result=probe(config(),lambda:None)
    assert set(result['observation'])=={'player','hand','history','round_scores','game_scores','turn','hand_sizes'}
    assert result['observation']['player']==0
    assert len(result['choices'])==2
    assert result['choices'][0]['seed']==result['choices'][1]['seed']
    assert result==probe(config(),lambda:None)
    assert all(len(c['candidates'])==5 for c in result['choices'])


def test_sqlite_legacy_unchanged_and_new_result_round_trip(tmp_path):
    store=ExperimentStore(tmp_path/'quality.sqlite')
    legacy={'legacy':'keep'};old=store.save(legacy)
    jobs=QualityJobs(store)
    result=wait(jobs,jobs.submit(config())['id'])
    assert result['status']=='completed'
    assert store.get(old)==legacy
    assert result==jobs.get(result['id'],full=True)
    assert result==QualityJobs(store).get(result['id'],full=True)
    assert result['baseline_commit']==BASELINE_COMMIT
    assert result['runtime']['source_sha256']
    assert result['runtime']['head_commit']
    interrupted=store.get(result['id']);interrupted['status']='running'
    other=store.save(interrupted)
    assert QualityJobs(store).get(other)['status']=='interrupted'
    with pytest.raises(KeyError):store.update('missing',{})
    jobs.close()


def test_cancel_and_single_worker(monkeypatch,tmp_path):
    entered=Event()
    def block(config,on_row,check,on_partial):
        entered.set()
        while True:
            check();sleep(.01)
    monkeypatch.setattr(jobs_module,'run_study',block)
    jobs=QualityJobs(ExperimentStore(tmp_path/'cancel.sqlite'))
    identifier=jobs.submit(config())['id'];assert entered.wait(2)
    with pytest.raises(RuntimeError):jobs.submit(config())
    jobs.cancel(identifier)
    result=wait(jobs,identifier)
    assert result['status']=='cancelled' and result['completed_games']==0
    assert result['summary']['settings'][0]['average_terminal_reward'] is None
    jobs.close()


def test_failure_and_timeout_never_mark_completed(monkeypatch,tmp_path):
    def fail(*args):raise ValueError('test')
    monkeypatch.setattr(jobs_module,'run_study',fail)
    jobs=QualityJobs(ExperimentStore(tmp_path/'failure.sqlite'))
    assert wait(jobs,jobs.submit(config())['id'])['status']=='failed'
    ticks=iter([0,2,2])
    monkeypatch.setattr(jobs_module,'monotonic',lambda:next(ticks))
    monkeypatch.setattr(jobs_module,'run_study',lambda c,row,check,partial:check())
    assert wait(jobs,jobs.submit(config(timeout_seconds=1))['id'])['status']=='timed_out'


def test_partial_game_costs_retained_but_not_reward_samples():
    cfg=config()
    partial={'setting':cfg.settings[0].identifier,'decisions':[{'elapsed_ns':2000000,'started_rollouts':4,
      'executed_rollouts':3,'accepted_rollouts':0,'timed_out':True}]}
    summary=summarize_study(cfg,[],[partial])['settings'][0]
    assert summary['games']==0 and summary['independent_deals']==0
    assert summary['average_terminal_reward'] is None
    assert summary['executed_rollouts']==3 and summary['timeout_decisions']==1


def test_completed_but_discarded_rollouts_are_counted(monkeypatch):
    import strategy_arena.strategies.monte_carlo as mc
    from strategy_arena.game.engine import Game
    from random import Random
    def partial(*args, on_game, **kwargs):
        on_game('started');on_game('finished')
        raise mc._BudgetExpired
    monkeypatch.setattr(mc, 'rollout_trial', partial)
    measured = module.MeasuredRollout(config().settings[0])
    measured.choose(Game(1).observe(0), Random(1))
    assert measured.samples[0]['executed_rollouts']==1
    assert measured.samples[0]['accepted_rollouts']==0


def test_api_saved_history_export_and_errors(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite')) as client:
        assert len(client.get('/api/quality-studies/presets').json())==2
        cfg=config().model_dump()
        assert client.post('/api/quality-studies/estimate',json=cfg).json()['games']==12
        response=client.post('/api/quality-studies',json=cfg)
        assert response.status_code==202
        identifier=response.json()['id']
        for _ in range(500):
            result=client.get('/api/quality-studies/'+identifier).json()
            if result['status'] not in ('running','cancelling'):break
            sleep(.01)
        assert result['status']=='completed' and result['completed_games']==12
        full=client.get('/api/quality-studies/'+identifier+'/export').json()
        assert len(full['results'])==12
        assert client.get('/api/experiments/'+identifier).json()['experiment_kind']==KIND
        assert client.get('/api/quality-studies').json()[0]['id']==identifier
        assert client.get('/api/quality-studies/missing').status_code==404
        assert client.post('/api/quality-studies',json={**cfg,'deal_seeds':[1,1]}).status_code==422
