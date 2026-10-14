"""固定相手2席とのリーグ。戦略定義と評価用設定を別モデルにする。"""
from dataclasses import asdict,replace
from hashlib import sha256
from random import Random
from time import perf_counter_ns
from typing import Literal
import json
import numpy as np
from pydantic import BaseModel,ConfigDict,Field,StrictInt,model_validator

from .runner import _play_game,derived_seed
from .rollout_quality import ROTATIONS,summarize_study
from .quality_jobs import QualityJobs
from .quality_statistics import complete_deals,paired_clusters,decision_sources
from ..strategies.declarative import StrategyDefinition,DeclarativeStrategy,DefinitionStore
from ..strategies.registry import create_strategy,strategy_names
from ..strategies.base import decide
from ..game.engine import Game
from ..game.rewards import terminal_rewards

KIND='strategy_arena_v1'
BASELINE='cf86d05c194b56254dfb97cd63252546e07c5e7d'
PARTITIONS={'development':0,'validation':1000000,'final':2000000}


class ArenaEntry(BaseModel):
    model_config=ConfigDict(extra='forbid')
    reference:str
    definition:StrategyDefinition|None=None

    @model_validator(mode='after')
    def valid(self):
        if self.definition:
            if self.reference!=self.definition.reference:raise ValueError('定義と固定版参照が一致しません')
        elif self.reference not in strategy_names() or isinstance(create_strategy(self.reference),DeclarativeStrategy):
            raise ValueError('宣言戦略は版と定義を固定してください')
        return self

    @property
    def identifier(self):return self.reference+(':'+self.definition.definition_hash if self.definition else '')
    @property
    def strategy_name(self):return self.definition.id if self.definition else self.reference
    @property
    def strategy_version(self):return self.definition.version if self.definition else create_strategy(self.reference).version
    @property
    def method(self):return 'arena'
    @property
    def theory_config(self):return self.definition.theory_config if self.definition else None
    def create_strategy(self):return DeclarativeStrategy(self.definition) if self.definition else create_strategy(self.reference)
    @property
    def total_budget(self):return getattr(self.create_strategy(),'parameters',{}).get('total_budget') if not self.definition else self.definition.total_budget
    @property
    def continuation(self):return self.definition.continuation if self.definition else getattr(self.create_strategy(),'parameters',{}).get('continuation','Random')
    @property
    def time_limit_ms(self):return None
    @property
    def min_trials(self):return 1
    @property
    def budget_family(self):
        if self.reference=='monte_carlo_rollout':return 'legacy'
        return 'budget' if self.total_budget else 'direct'
    @property
    def rollout_bound(self):return 1200 if self.reference=='monte_carlo_rollout' else 15*(self.total_budget or 0)


class ArenaPlan(BaseModel):
    model_config=ConfigDict(extra='forbid')
    baseline_commit:Literal[BASELINE]=BASELINE
    name:str=Field(default='Codex Strategy Arena',max_length=100)
    settings:list[ArenaEntry]=Field(min_length=1,max_length=8)
    opponent_entries:tuple[ArenaEntry,ArenaEntry]
    deal_seeds:list[StrictInt]=Field(min_length=1,max_length=20)
    policy_seed:int=Field(default=42,strict=True,ge=0,le=9007199254740991)
    seed_partition:Literal['development','validation','final']='development'
    include_expensive:bool=Field(default=False,strict=True)
    analyze_position:bool=True
    capture_rank_trace:bool=Field(default=False,strict=True)
    timeout_seconds:int=Field(default=180,strict=True,ge=1,le=300)

    @property
    def opponents(self):return tuple(e.strategy_name for e in self.opponent_entries)

    @model_validator(mode='after')
    def valid(self):
        if len({s.identifier for s in self.settings})!=len(self.settings):raise ValueError('重複した参加設定です')
        base=PARTITIONS[self.seed_partition]
        if len(set(self.deal_seeds))!=len(self.deal_seeds) or any(not base<=s<base+1000000 for s in self.deal_seeds):raise ValueError('配札seedの用途範囲・重複が不正です')
        all_entries=[*self.settings,*self.opponent_entries]
        if not self.include_expensive and any(e.rollout_bound for e in all_entries):raise ValueError('探索戦略の参加には高コスト戦略を許可してください')
        if arena_estimate(self)['games']>360 or arena_estimate(self)['rollout_upper_bound']>250000:raise ValueError('最大360対局・25万Rollout以内へ分割してください')
        return self


class ArenaRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    participants:list[str]=Field(min_length=1,max_length=8)
    opponents:tuple[str,str]=('Random','Heuristic')
    deals:int=Field(default=2,strict=True,ge=1,le=20)
    seed_partition:Literal['development','validation','final']='development'
    start_offset:int=Field(default=100,strict=True,ge=0,le=999980)
    policy_seed:int=Field(default=42,strict=True,ge=0,le=9007199254740991)
    include_expensive:bool=Field(default=False,strict=True)
    timeout_seconds:int=Field(default=180,strict=True,ge=1,le=300)

    capture_rank_trace:bool=Field(default=False,strict=True)

    def resolve(self,definitions):
        def entry(ref):return ArenaEntry(reference=ref,definition=definitions.get(ref) if '@' in ref else None)
        return ArenaPlan(settings=[entry(r) for r in self.participants],opponent_entries=tuple(entry(r) for r in self.opponents),
            deal_seeds=[PARTITIONS[self.seed_partition]+self.start_offset+i for i in range(self.deals)],
            policy_seed=self.policy_seed,seed_partition=self.seed_partition,include_expensive=self.include_expensive,timeout_seconds=self.timeout_seconds,capture_rank_trace=self.capture_rank_trace)


def arena_estimate(config,historical=()):
    games=6*len(config.deal_seeds)*len(config.settings)
    rollouts=6*len(config.deal_seeds)*sum(s.rollout_bound+sum(o.rollout_bound for o in config.opponent_entries) for s in config.settings)
    probe_rollouts=sum(40 if s.reference=='monte_carlo_rollout' else (s.total_budget or 0) for s in config.settings) if config.analyze_position else 0
    rollouts+=probe_rollouts
    seconds=games*.05+rollouts*.0006
    return {'games':games,'independent_deals':len(config.deal_seeds),'rotations':6,'rollout_upper_bound':rollouts,'probe_rollout_upper_bound':probe_rollouts,
            'estimated_seconds':seconds,'estimated_seconds_range':[seconds*.5,seconds*2],'estimated_storage_bytes':games*8192+131072,
            'note':'各参加候補＋固定した相手2役の全6役割順。直接評価も実測で校正してください。',
            'resource_note':'未校正の参考モデル。JSONのみの容量概算。時間・容量の上限保証ではありません。'}


class Captured:
    def __init__(self,entry):
        self.strategy=entry.create_strategy();self.name,self.version=self.strategy.name,self.strategy.version;self.samples=[]
    def choose(self,observation,rng):
        start=perf_counter_ns();decision=decide(self.strategy,observation,rng,True)
        meta=(decision.details.optional_metadata or {}) if decision.details else {}
        self.samples.append({'elapsed_ns':perf_counter_ns()-start,'started_rollouts':meta.get('started_games',0),
            'executed_rollouts':meta.get('executed_games',0),'accepted_rollouts':meta.get('completed_games',0),'timed_out':meta.get('timed_out',False)})
        return replace(decision,details=None)


def run_arena(config,on_row=lambda r:None,check=lambda:None,on_partial=lambda r:None):
    for index,deal in enumerate(config.deal_seeds):
        for rotation,roles in enumerate(ROTATIONS):
            for setting in config.settings:
                check();entries=[setting,*config.opponent_entries];policies=[Captured(entries[role]) for role in roles]
                # 配札seedを方策rngへ混ぜない。戦略に渡すのは観測とこの独立系列だけ。
                rngs=[Random(derived_seed(config.policy_seed,f'arena-policy-v1:{index}:{role}')) for role in roles]
                names=tuple(p.name for p in policies);seat=roles.index(0);started=perf_counter_ns()
                try:game,_,_=_play_game(deal,names,False,False,strategies=policies,rngs=rngs,check=check)
                except Exception:
                    on_partial({'setting':setting.identifier,'deal_id':str(deal),'rotation':rotation,'game_elapsed_ns':perf_counter_ns()-started,'decisions':policies[seat].samples});raise
                trace={}
                if config.capture_rank_trace:
                    from .zigzag_analysis import rank_trace
                    trace={'rank_trace':rank_trace(deal,game.observe(seat).history,seat)}
                on_row({**trace,'setting':setting.identifier,'deal_id':str(deal),'seed':deal,'rotation':rotation,'roles':roles,'seat':seat,
                    'strategies':names,'rollout_parameters':setting.model_dump(mode='json'),'strategy_version':setting.strategy_version,
                    'scores':game.observe(0).game_scores,'winners':game.winners,'terminal_rewards':terminal_rewards(game.winners),
                    'game_elapsed_ns':perf_counter_ns()-started,'decisions':policies[seat].samples,
                    'role_records':[{'role':role,'seat':p,'reference':entries[role].reference,'decisions':policies[p].samples} for p,role in enumerate(roles)]})


def arena_probe(config,check):
    game=Game(42)
    for _ in range(12):game.play(tuple(game.observe(p).legal_actions[0] for p in range(3)))
    obs=game.observe(0);choices=[]
    for setting in config.settings:
        check();d=decide(setting.create_strategy(),obs,Random(derived_seed(config.policy_seed,'arena-public-probe')),True)
        choices.append({'setting':setting.identifier,'selected_card':asdict(d.card),'decision':asdict(d)})
    return {'observation':asdict(obs),'generation':'公開固定seed42の人工局面。非公開の評価配札ではない。','choices':choices}


def arena_summary(config,rows,partials=()):
    summary=summarize_study(config,rows,partials)
    for setting,item in zip(config.settings,summary['settings']):
        valid=complete_deals(config,rows,setting);used=[r for group in valid.values() for r in group]
        item.update(reference=setting.reference,loss_rate=1-item['sole_win_rate']-item['joint_win_rate'] if item['games'] else None,
            opponents=[e.reference for e in config.opponent_entries],seats=[{'seat':p,'games':len(rs),
             'average_terminal_reward':float(np.mean([r['terminal_rewards'][p] for r in rs])) if rs else None} for p in range(3) if (rs:=[r for r in used if r['seat']==p])])
    return summary


def compare_arena(first,second,first_name,second_name):
    a,b=ArenaPlan.model_validate(first['config']),ArenaPlan.model_validate(second['config'])
    reasons=[]
    for key in ('baseline_commit','policy_seed','seed_partition','opponent_entries'):
        if a.model_dump()[key]!=b.model_dump()[key]:reasons.append(key+'が一致しません')
    for key in ('rule_version','reward_version','information_condition','runner_seed_scheme'):
        if first.get(key)!=second.get(key) or first.get(key) is None:reasons.append(key+'が一致しません')
    if decision_sources(first)!=decision_sources(second):reasons.append('実装hashが一致しません')
    required={'strategies/declarative.py','experiments/arena.py','game/engine.py'}
    if not required<=decision_sources(first).keys() or not required<=decision_sources(second).keys():reasons.append('実装hashが不足しています')
    left=next((s for s in a.settings if s.identifier==first_name),None);right=next((s for s in b.settings if s.identifier==second_name),None)
    if left is None or right is None:raise ValueError('設定がありません')
    # 同じ配札でも方策のindexが違うと乱数条件が揃わない。
    if a.deal_seeds!=b.deal_seeds:reasons.append('配札の順序・集合が一致しません')
    if reasons:return {'comparable':False,'reasons':reasons,'difference':None,'ci95':None,'independent_deals':0}
    return paired_clusters(complete_deals(a,first['results'],left),complete_deals(b,second['results'],right),left,right,a.policy_seed)


def arena_jobs(store):
    return QualityJobs(store,kind=KIND,config_model=ArenaPlan,runner=run_arena,prober=arena_probe,summarizer=arena_summary,planner=arena_estimate,seed_scheme='arena-policy-v1')
