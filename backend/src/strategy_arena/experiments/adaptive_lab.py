"""適応方式の事前登録・保存・独立三標本。旧実験行を変更しない。"""
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
from typing import Literal
from uuid import uuid4
from threading import Thread,Event
from time import monotonic
import json,sqlite3
from pydantic import Field,model_validator
from .reliability_lab import ReliabilityConfig,ReliabilityJobs,restore_observation
from .stratification_lab import StratificationJobs,collect
from .decision_analysis import decision_positions
from .adaptive_analysis import analyze_adaptive,adaptive_summary,execution_meter
from .evolution import digest
from .design_lab import now
from .rollout_quality import runtime_info
from .evidence_lab import deal_identity
from ..game.rules import RULE_VERSION
from ..game.rewards import REWARD_VERSION

class AdaptiveConfig(ReliabilityConfig):
    name:str=Field(default='適応サンプリング独立参照パイロット',min_length=1,max_length=100)
    start_offset:int=Field(default=16000,strict=True,ge=0,le=1999900)
    partition:Literal['development','validation']='development'
    budgets:list[Literal[16,32,64,128,256]]=Field(default=[16,32],min_length=1,max_length=5)
    reference_worlds:int=Field(default=32,strict=True,ge=16,le=256)
    final_worlds:int=Field(default=32,strict=True,ge=16,le=256)
    initial_worlds:int=Field(default=16,strict=True,ge=16,le=32)
    batch_worlds:int=Field(default=16,strict=True,ge=1,le=64)
    gap_threshold:float=Field(default=.5,ge=0,le=4,allow_inf_nan=False)
    uncertainty_z:float=Field(default=2,ge=1,le=5,allow_inf_nan=False)
    minimum_gap:float=Field(default=.05,ge=0,le=1,allow_inf_nan=False)
    budget_mode:Literal['max_worlds','total_games']='max_worlds'
    games_per_policy:int=Field(default=1024,strict=True,ge=272,le=4352)
    cross_models:bool=Field(default=False,strict=True)
    max_derived_games:int=Field(default=40000,strict=True,ge=1000,le=80000)
    historical_limit:int=Field(default=0,strict=True,ge=0,le=2)
    hypothesis:str=Field(default='適応的な追加標本が同じ最大世界数または派生対局上限で固定方式より効率的かを調べる。優位性は未検証。',min_length=1,max_length=2000)

    @model_validator(mode='after')
    def adaptive_valid(self):
        if self.initial_worlds>min(self.budgets):raise ValueError('初期世界数は最小予算以内')
        legal_upper=17 if self.diagnostic_source_id else 17-min(self.turns)
        if self.budget_mode=='total_games' and self.games_per_policy<legal_upper*self.initial_worlds:raise ValueError('全合法手の初期世界数を評価できる総派生対局予算が必要')
        if self.partition=='development' and self.start_offset+self.deals>1000000:raise ValueError('開発配札は0〜999999')
        if self.partition=='validation' and not 1000000<=self.start_offset<2000000:raise ValueError('検証配札は1000000〜1999999')
        if adaptive_estimate(self)['derived_games_upper']>self.max_derived_games:raise ValueError('派生対局の事前上限を超えます')
        if self.evaluation_worlds!=64 or self.safety_tolerance!=0:raise ValueError('旧互換フィールドevaluation_worlds/safety_toleranceは既定値に固定。reference_worlds/final_worldsを使用')
        return self

def adaptive_estimate(c):
    # 診断札は最大17枚、新規札は指定手番の最大手札枚数。部分的な候補ブロックは実行しない。
    k=17 if c.diagnostic_source_id else 17-min(c.turns)
    selection_per=sum((k*b if c.budget_mode=='max_worlds' else min(k*b,c.games_per_policy)) for b in c.budgets)*3*c.repeats*len(c.models)
    selection=c.max_positions*selection_per
    overhead=c.max_positions*k*(c.reference_worlds+c.final_worlds)*len(c.models)
    total=selection+overhead
    return {'independent_fresh_deals':c.deals,'positions_upper':c.max_positions,'legal_count_upper':k,
            'selection_games_upper':selection,'research_overhead_games_upper':overhead,'derived_games_upper':total,
            'simulated_turns_upper':total*15,'collection_games':c.deals*len(c.collectors),
            'estimated_seconds_range':[total*.0005,total*.003+c.deals*len(c.collectors)*.1],
            'note':'候補×世界×方式×予算×反復×モデル。選択の方式間は再計算し実コストを記録。参照・最終評価は共有研究オーバーヘッド。時間は未校正。'}

class AdaptiveJobs(ReliabilityJobs):
    kind='adaptive_sampling_v1'
    config_type=AdaptiveConfig
    estimate=staticmethod(adaptive_estimate)

    def plan_extras(self,c):return {}
    def begin_run(self,v):return None
    def finish_run(self,v,token):pass

    def result_content(self,v):return {**super().result_content(v),'execution_cost':v.get('execution_cost')}

    def start(self,identifier,expected_hash):
        with self.lock:
            if self.active:raise RuntimeError('適応実験は1件ずつ')
            v=self.get(identifier)
            if v['status']!='Registered' or v['condition_hash']!=expected_hash:raise ValueError('登録状態・Hash不一致')
            if v['snapshot']['sources']!=runtime_info()['source_sha256']:raise ValueError('登録後に実装が変わりました')
            c=self.config_type.model_validate(v['config']);v.pop('id',None);v.update(status='Running',inventory=[],collection_summary=None,cluster_summary=None)
            v['execution_cost']={s:{'started_games':0,'completed_games':0,'completed_simulated_turns':0} for s in ('policy','reference','final')}
            v['execution_cost'].update(stage='policy',limit=c.max_derived_games,scope='手番数は完了派生対局の実行ターン数。中断中の1対局の部分手番は未計測。収集軌跡は別。')
            self.active=identifier;self.owned.add(identifier);self.stop=Event();self.store.update(identifier,v)
        def worker():
            started=monotonic();last=[started];token=execution_meter.set(v['execution_cost']);run_token=self.begin_run(v)
            def check():
                if self.stop.is_set():raise InterruptedError('Cancelled')
                if monotonic()-started>c.timeout_seconds:raise InterruptedError('TimedOut')
            def persist():v['elapsed_seconds']=monotonic()-started;self.store.update(identifier,v)
            def progress():
                v['progress']+=1
                if monotonic()-last[0]>=.25:persist();last[0]=monotonic()
            try:
                records,observations,summary=self.collect_positions(c,check,progress,v['snapshot']);v.update(inventory=records,collection_summary=summary);persist()
                for item in self.position_results(c,records,observations,check,progress):v['positions'].append(item);persist()
                v['cluster_summary']=self.summarize_positions(v['positions']);v['status']='Completed'
            except InterruptedError as e:v['status']=str(e)
            except Exception as e:v.update(status='Failed',error=f'{type(e).__name__}: {e}')
            finally:
                self.finish_run(v,run_token)
                v['result_hash']=digest(self.result_content(v));persist();execution_meter.reset(token)
                with self.lock:self.active=None
        Thread(target=worker,daemon=True,name='adaptive-sampling').start();return self.get(identifier)

    def register(self,c):
        estimate=self.estimate(c)
        if estimate['estimated_seconds_range'][1]>c.timeout_seconds:raise ValueError('上側時間見積もりを120秒以内に縮小してください')
        historical=self.historical(c);sources=runtime_info()['source_sha256']
        hashes=[deal_identity(s,sources) for s in range(c.start_offset,c.start_offset+c.deals)]
        if len(set(hashes))!=len(hashes):raise ValueError('実配札Hashが重複')
        if set(hashes)&{p['deal_hash'] for p in historical}:raise ValueError('新規配札が診断配札と重複')
        snapshot={'config':c.model_dump(mode='json'),'sources':sources,'rule':RULE_VERSION,'reward':REWARD_VERSION,'created_at':now(),
                  'historical':historical,'deal_hashes':hashes,'seed_partition':c.partition,'metric':'terminal_reward',
                  'methods':['Fixed','Gap-Adaptive','Uncertainty-Adaptive'],'adaptation_scope':'within-position','sampler':'uniform-unseen-v1','sampling':'局面内のみ。3段階は異なるdomain-derived seed、反復間も分離。',
                  'stop_rule':'gap閾値、または全競合への対応差>z*SE+minimum_gap。探索的停止で逐次的な誤選択保証なし。',
                  'tie_break':'rank昇順、同rankはsuit昇順','unit':'Rollout=候補1枚から終局まで1派生対局。手番=3席同時の1ターン。',
                  'hypothesis':c.hypothesis,'regret':'独立参照標本で選択した有限標本参照札をさらに独立な最終標本で評価。負値を許す。',
                  'baseline_commit':runtime_info()['head_commit'],**self.plan_extras(c)}
        with self.lock,closing(sqlite3.connect(self.store.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS adaptive_deals(deal_hash TEXT PRIMARY KEY,seed INTEGER,job_id TEXT)')
            for h in hashes:
                if db.execute('SELECT 1 FROM adaptive_deals WHERE deal_hash=?',(h,)).fetchone():raise ValueError('実配札Hashは予約済み')
            old_seeds=set()
            for _,payload in db.execute('SELECT id,payload FROM experiments'):
                v=json.loads(payload);cfg=v.get('config',{});old_seeds.update(cfg.get('deal_seeds',[]))
                if isinstance(cfg.get('start_offset'),int) and isinstance(cfg.get('deals'),int):old_seeds.update(range(cfg['start_offset'],cfg['start_offset']+cfg['deals']))
                if any(p.get('deal_hash') in hashes for p in v.get('positions',[])):raise ValueError('実配札Hashは既存実験で使用済み')
            old_seeds.update(s for s, in db.execute('SELECT seed FROM middle_seed_reservations'))
            old_seeds.update(s for s, in db.execute('SELECT seed FROM design_seeds'))
            if any(deal_identity(s,sources) in hashes for s in old_seeds):raise ValueError('配札は既存実験・計画で使用済み')
            identifier=str(uuid4());value={'experiment_kind':self.kind,'status':'Registered','config':c.model_dump(mode='json'),
                'snapshot':snapshot,'condition_hash':digest(snapshot),'estimate':estimate,'created_at':now(),'positions':[],
                'reproduction':None,'progress':0,'elapsed_seconds':0,'error':None}
            db.execute('INSERT INTO experiments VALUES (?,?)',(identifier,json.dumps(value)))
            db.executemany('INSERT INTO adaptive_deals VALUES (?,?,?)',[(h,c.start_offset+i,identifier) for i,h in enumerate(hashes)])
            db.executemany('INSERT INTO middle_seed_reservations VALUES (?,?)',[(c.start_offset+i,identifier) for i in range(c.deals)])
        return self.get(identifier)

    def collect_positions(self,c,check,progress,snapshot):
        records,observations,summary=collect(c,check,progress)
        for r in records:r.update(population='fresh',seed_partition=c.partition)
        historical=deepcopy(snapshot['historical'])
        for r in historical:observations[r['position_hash']]=restore_observation(r['observation'])
        summary.update(diagnostic_positions=len(historical),diagnostic_deals=len({p['deal_hash'] for p in historical}))
        return records+historical,observations,summary

    def position_results(self,c,records,observations,check,progress):
        historical=[r for r in records if r['population']=='diagnostic'];fresh=[r for r in records if r['population']=='fresh']
        selected=historical+decision_positions(fresh,c.max_positions-len(historical),0)
        for r in selected:
            obs=observations[r['position_hash']]
            yield {**r,'position_id':r['position_hash'],'observation':asdict(obs),'labels':['中間得点'] if r['stratum']['strict_middle'] else [],
                   'search':{'reversals':[]},'validation':None,'adaptive':analyze_adaptive(obs,c,r['position_hash'],check,progress)}

    summarize_positions=staticmethod(adaptive_summary)

    def get(self,identifier):
        v=StratificationJobs.get(self,identifier)
        v['recommendations']=[{'action':'独立配札を追加して固定方式との差と計算量を併記する','reason':'少数の局面と選択反復から優位性を確定しない。'}]
        positions=v['positions'];keys=('derived_games','simulated_turns','simulated_player_actions','elapsed_seconds')
        v['cost_summary']={stage:{k:sum(p['adaptive'][stage][k] for p in positions) for k in keys} for stage in ('selection_cost','overhead_cost','total_cost')}
        v['cost_summary']['scope']='保存済み完了局面だけ。中断中の部分局面のコストは含まない。収集軌跡は別項目。'
        v['cost_summary']['collection_games_completed']=v.get('collection_summary',{}).get('independent_deals',0)*len(v['config']['collectors']) if v.get('collection_summary') else 0
        v['cost_summary']['collection_simulated_turns']=v['cost_summary']['collection_games_completed']*15
        v['cost_summary']['experiment_elapsed_seconds']=v['elapsed_seconds']
        return v
