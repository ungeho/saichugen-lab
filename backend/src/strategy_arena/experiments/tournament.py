"""既存登録戦略だけの三人実戦大会。選抜・戦略本体・旧記録を変更しない。"""
from collections import defaultdict
from contextlib import closing
from dataclasses import replace
from itertools import combinations_with_replacement, permutations
from math import log, sqrt
from random import Random
import json, sqlite3
from time import perf_counter_ns
from typing import Literal
from uuid import uuid4
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .adaptive_lab import AdaptiveJobs
from .adaptive_analysis import execution_meter
from .design_lab import now
from .evidence_lab import deal_identity
from .evolution import digest
from .rollout_quality import runtime_info, interval
from .runner import _play_game, derived_seed
from ..game.rewards import terminal_rewards, REWARD_VERSION
from ..game.rules import RULE_VERSION
from ..strategies.registry import create_strategy

PARTICIPANTS=('Random','Heuristic','ScoreAware','hybrid_combined')
EXCLUDED={'monte_carlo_rollout Fixed128':'通常登録戦略のMAX_TRIALS=64。研究用Fixed128は局面評価であり、既存の通常対戦戦略ではない。64を128と呼ばず除外。'}

def compositions(mode='all'):
    all_rows=list(combinations_with_replacement(PARTICIPANTS,3))
    # 全構成が予算に収まらない場合の事前削減規則。各戦略の出現回数を対称に保つ。
    return all_rows if mode=='all' else [r for r in all_rows if len(set(r)) in (1,3)]

def schedule(mode='all'):
    return [{'composition':list(c),'assignment':list(a),'rotation':i}
            for c in compositions(mode) for i,a in enumerate(sorted(set(permutations(c))))]

class TournamentConfig(BaseModel):
    model_config=ConfigDict(extra='forbid')
    tournament_version:Literal[45]=45
    name:str=Field(default='Final Strategy Tournament',min_length=1,max_length=100)
    partition:Literal['development','validation']='development'
    deal_seeds:list[str]=Field(default=['45000'],min_length=1,max_length=20)
    policy_seed:str='18446744073709551045'
    composition_mode:Literal['all','symmetric_reduced']='all'
    timeout_seconds:int=Field(default=120,strict=True,ge=1,le=900)
    max_derived_games:int=Field(default=100000,strict=True,ge=1,le=2000000)
    pilot_seconds_per_deal:float|None=Field(default=None,gt=0,allow_inf_nan=False)
    prior_deal_hashes:list[str]=Field(default_factory=list,max_length=20000)
    inventory_note:str=Field(default='',max_length=3000)
    @field_validator('policy_seed')
    @classmethod
    def seed64(cls,v):
        if not v.isascii() or not v.isdecimal() or str(int(v))!=v or int(v)>2**64-1:raise ValueError('seedは正規化されたuint64十進文字列')
        return v
    @field_validator('deal_seeds')
    @classmethod
    def deal_seed64(cls,v):
        for s in v:cls.seed64(s)
        if len(set(v))!=len(v):raise ValueError('配札seed重複')
        return v
    @model_validator(mode='after')
    def bounded(self):
        lo,hi=(0,1000000) if self.partition=='development' else (1000000,2000000)
        if any(not lo<=int(s)<hi for s in self.deal_seeds):raise ValueError('配札区分不一致')
        if estimate(self)['games']>1280:raise ValueError('最大1280試合')
        if self.partition=='validation':
            if not self.prior_deal_hashes or not self.inventory_note or self.pilot_seconds_per_deal is None:raise ValueError('検証には既使用配札照合とPilot時間予測が必要')
            if estimate(self)['conservative_seconds']>self.timeout_seconds:raise ValueError('保守予測が時間上限を超える')
        return self

def estimate(c):
    rows=schedule(c.composition_mode);hybrid_seats=sum(r['assignment'].count('hybrid_combined') for r in rows)
    return {'independent_deals':len(c.deal_seeds),'compositions':len(compositions(c.composition_mode)),
            'games':len(rows)*len(c.deal_seeds),'derived_games_upper':hybrid_seats*15*64*len(c.deal_seeds),
            'simulated_turns_upper':hybrid_seats*64*120*len(c.deal_seeds),
            'conservative_seconds':c.pilot_seconds_per_deal*len(c.deal_seeds) if c.pilot_seconds_per_deal else None,
            'note':'全unique席順。配札等重み。Hybrid既定64総派生対局/判断、Fixed128は使用不能。'}

class Measured:
    def __init__(self,name,check):
        self.strategy=create_strategy(name);self.name=name;self.version=self.strategy.version;self.samples=[];self.check=check
    def choose(self,observation,rng):
        self.check();meter=execution_meter.get();search=self.name=='hybrid_combined'
        if search and meter and meter['policy']['started_games']+64>meter['limit']:raise InterruptedError('BudgetExceeded')
        start=perf_counter_ns()
        d=self.strategy.choose_detailed(observation,rng) if search else self.strategy.choose(observation,rng)
        ns=perf_counter_ns()-start;meta=(d.details.optional_metadata or {}) if d.details else {}
        games=meta.get('executed_games',0)
        if meter:
            meter['policy']['started_games']+=meta.get('started_games',0)
            meter['policy']['completed_games']+=games
            meter['policy']['completed_simulated_turns']+=games*(15-observation.turn)
        self.samples.append({'turn':observation.turn,'rank':d.card.rank,'suit':d.card.suit,'decision_ns':ns,
                             'derived_games':games,'simulated_turns':games*(15-observation.turn)})
        self.check();return replace(d,details=None)

def play(c,seed,item,check=lambda:None):
    policies=[Measured(n,check) for n in item['assignment']]
    # occurrenceは同名複製を区別。評価用配札seedをAPIに載せず専用政策乱数だけを渡す。
    roles=[f'{n}:{item["assignment"][:p].count(n)}' for p,n in enumerate(item['assignment'])]
    rngs=[Random(derived_seed(int(c.policy_seed),f'tournament:{seed}:{role}')) for role in roles]
    start=perf_counter_ns()
    try:game,_,_=_play_game(int(seed),tuple(item['assignment']),False,False,strategies=policies,rngs=rngs,check=check)
    except BaseException as error:
        error.tournament_partial={'deal_id':seed,**item,'decision_samples':[p.samples for p in policies],'wall_seconds':(perf_counter_ns()-start)/1e9}
        raise
    return {'deal_id':seed,**item,'scores':list(game.observe(0).game_scores),'winners':list(game.winners),
            'terminal_rewards':list(terminal_rewards(game.winners)),'wall_seconds':(perf_counter_ns()-start)/1e9,
            'decision_samples':[p.samples for p in policies]}

def summary(c,rows,complete):
    expected=schedule(c.composition_mode);keys=lambda r:(tuple(r['composition']),tuple(r['assignment']))
    bydeal=defaultdict(list)
    for r in rows:bydeal[r['deal_id']].append(r)
    completed=[s for s in c.deal_seeds if len(bydeal[s])==len(expected) and {keys(r) for r in bydeal[s]}=={keys(r) for r in expected}]
    out={'primary_finalized':complete and len(completed)==len(c.deal_seeds),'complete_deals':len(completed),
         'partial_deals':sum(bool(bydeal[s]) and s not in completed for s in c.deal_seeds),'not_started_deals':sum(not bydeal[s] for s in c.deal_seeds),
         'recorded_games':len(rows),'ranking':None,'comparisons':None,'closure':'未完了のため主要順位・結論を確定しない。',
         'uncertainty':'独立単位は配札。CIは配札bootstrapの探索的95%区間。選択の多重性は別途Bonferroni-Hoeffding境界で保守判定。同等性・普遍的強さを保証しない。'}
    if not out['primary_finalized']:return out
    clusters={n:[] for n in PARTICIPANTS};ranking=[]
    for name in PARTICIPANTS:
        flat=[];metrics=defaultdict(list)
        for seed in completed:
            seats=[(r,p) for r in bydeal[seed] for p,n in enumerate(r['assignment']) if n==name]
            clusters[name].append(float(np.mean([r['terminal_rewards'][p] for r,p in seats])))
            for key,fn in [('sole_win_rate',lambda r,p:int(p in r['winners'] and len(r['winners'])==1)),
                           ('two_way_win_rate',lambda r,p:int(p in r['winners'] and len(r['winners'])==2)),
                           ('three_way_win_rate',lambda r,p:int(len(r['winners'])==3)),
                           ('loss_rate',lambda r,p:int(p not in r['winners'])),('average_score',lambda r,p:r['scores'][p])]:
                metrics[key].append(float(np.mean([fn(r,p) for r,p in seats])))
            flat.extend((r,p) for r,p in seats)
        decisions=[d for r,p in flat for d in r['decision_samples'][p]];times=[d['decision_ns']/1e6 for d in decisions]
        ranking.append({'strategy':name,'mean_reward':float(np.mean(clusters[name])),
                        'reward_ci95':interval(clusters[name],derived_seed(int(c.policy_seed),'ci:'+name)),
                        **{k:float(np.mean(v)) for k,v in metrics.items()},'seat_appearances':len(flat),'independent_deals':len(completed),
                        'decision_ms':{'mean':float(np.mean(times)),'p95':float(np.quantile(times,.95)),'max':max(times)},
                        'game_seconds':float(np.mean([r['wall_seconds'] for r,p in flat])),
                        'derived_games':sum(d['derived_games'] for d in decisions),'simulated_turns':sum(d['simulated_turns'] for d in decisions),
                        'action_by_period':{period:{'decisions':len(ds),'mean_rank':float(np.mean([d['rank'] for d in ds]))} for period,ds in
                          [(label,[d for d in decisions if lo<=d['turn']<hi]) for label,lo,hi in [('early',0,5),('middle',5,10),('late',10,15)]]}})
    comparisons=[];radius=8*sqrt(log(2*6/.05)/(2*len(completed)))
    for a,b in combinations_with_replacement(PARTICIPANTS,2):
        if a==b:continue
        diffs=[x-y for x,y in zip(clusters[a],clusters[b])];mean=float(np.mean(diffs))
        comparisons.append({'a':a,'b':b,'difference':mean,'ci95':interval(diffs,derived_seed(int(c.policy_seed),a+':'+b)),
                            'simultaneous_bound':[max(-4,mean-radius),min(4,mean+radius)],'independent_deals':len(completed)})
    ranking.sort(key=lambda r:(-r['mean_reward'],r['strategy']));best=ranking[0]['strategy']
    def lower(a,b):
        r=next(r for r in comparisons if {r['a'],r['b']}=={a,b});return r['simultaneous_bound'][0] if r['a']==a else -r['simultaneous_bound'][1]
    supported=[n for n in PARTICIPANTS if n!='Random' and lower(n,'Random')>0]
    promising=best!='Random' and all(lower(best,n)>0 for n in PARTICIPANTS if n!=best)
    out.update(ranking=ranking,comparisons=comparisons,clusters=clusters,
               closure='A：有力戦略を暫定選定して終了' if promising else 'B：勝者未確定として終了' if supported else 'C：Randomに対する優位性未確認として終了',
               observed_best=best,practical_candidate=min(ranking,key=lambda r:r['decision_ms']['mean'])['strategy'])
    return out

class TournamentJobs(AdaptiveJobs):
    kind='final_tournament_v1';config_type=TournamentConfig;estimate=staticmethod(estimate)
    def register(self,c):
        sources=runtime_info()['source_sha256'];hashes=[deal_identity(int(s),sources) for s in c.deal_seeds]
        if len(set(hashes))!=len(hashes) or set(hashes)&set(c.prior_deal_hashes):raise ValueError('実配札Hashは重複・既使用')
        manifest=[{'name':n,'version':create_strategy(n).version,'parameters':getattr(create_strategy(n),'parameters',{})} for n in PARTICIPANTS]
        plan={'version':'final-tournament-v1','config':c.model_dump(mode='json'),'assignments':schedule(c.composition_mode),'deal_hashes':hashes,
              'manifest':manifest,'excluded':EXCLUDED,'rule':RULE_VERSION,'reward':REWARD_VERSION,'sources':sources,
              'hybrid_selection':'Validationを参照せず登録済みcombined既定64を単純規則で選定',
              'closure_rule':'A=観測首位が全主要比較の同時保守下限>0、B=少なくとも一戦略のRandom差下限>0、他はC。全て研究終了。',
              'statistics':'配札内全席平均→配札等重み。探索的bootstrap2000と6比較Bonferroni-Hoeffding（差の幅8）。',
              'information':'本人のGame.observeのみ。実手札や評価seedを観測へ追加しない。'}
        snap={'config':c.model_dump(mode='json'),'sources':sources,'study_plan':plan,'study_plan_hash':digest(plan),'baseline_commit':runtime_info()['head_commit']}
        with self.lock,closing(sqlite3.connect(self.store.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');db.execute('CREATE TABLE IF NOT EXISTS tournament_deals(hash TEXT PRIMARY KEY,seed TEXT,job_id TEXT)')
            for _,p in db.execute('SELECT id,payload FROM experiments'):
                old=json.loads(p);cfg=old.get('config',{});used={str(s) for s in cfg.get('deal_seeds',[])}
                if isinstance(cfg.get('start_offset'),int) and isinstance(cfg.get('deals'),int):used.update(str(s) for s in range(cfg['start_offset'],cfg['start_offset']+cfg['deals']))
                if used&set(c.deal_seeds) or set(hashes)&set(old.get('snapshot',{}).get('deal_hashes',[])):raise ValueError('配札は使用/予約済み')
            for h in hashes:
                if db.execute('SELECT 1 FROM tournament_deals WHERE hash=?',(h,)).fetchone():raise ValueError('Hash予約済み')
            identifier=str(uuid4());v={'experiment_kind':self.kind,'status':'Registered','config':c.model_dump(mode='json'),'snapshot':snap,
                'condition_hash':digest(snap),'estimate':estimate(c),'created_at':now(),'positions':[],'partial_games':[],'progress':0,'elapsed_seconds':0,'error':None}
            db.execute('INSERT INTO experiments VALUES (?,?)',(identifier,json.dumps(v)));db.executemany('INSERT INTO tournament_deals VALUES (?,?,?)',zip(hashes,c.deal_seeds,[identifier]*len(hashes)))
        return self.get(identifier)
    def begin_run(self,v):self.run_value=v
    def result_content(self,v):return {k:v.get(k) for k in ('positions','partial_games','execution_cost')}
    def collect_positions(self,c,check,progress,snapshot):return [],{},None
    def position_results(self,c,records,observations,check,progress):
        for s in c.deal_seeds:
            for item in schedule(c.composition_mode):
                check()
                try:row=play(c,s,item,check)
                except BaseException as error:
                    if hasattr(error,'tournament_partial'):self.run_value['partial_games'].append(error.tournament_partial)
                    raise
                progress();yield row
    def summarize_positions(self,positions):return None
    def get(self,identifier):
        v=self.store.get(identifier)
        if not v or v.get('experiment_kind')!=self.kind:raise KeyError(identifier)
        if digest(v['snapshot'])!=v['condition_hash'] or v['config']!=v['snapshot']['config'] or (v.get('result_hash') and digest(self.result_content(v))!=v['result_hash']):v['status']='Invalidated'
        if v['status']=='Running' and identifier not in self.owned:v['status']='Interrupted'
        c=TournamentConfig.model_validate(v['config']);v['tournament_evidence']=summary(c,v['positions'],v['status']=='Completed')
        return {'id':identifier,**v}
