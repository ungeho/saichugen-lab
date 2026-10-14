"""単一ローカルワーカー。専用の事前登録と探索証拠の参照連携。"""
from contextlib import closing
from dataclasses import asdict
from threading import Lock,Event,Thread
from time import monotonic,sleep
from random import Random
from collections import defaultdict
import sqlite3,json
import numpy as np
from pydantic import Field,model_validator
from .design_lab import StrictModel,PlanSpec,now
from .evolution import digest
from .runner import derived_seed
from .rollout_quality import ROTATIONS,runtime_info
from .zigzag_analysis import rank_slots
from .middle_analysis import LIGHT,evaluate_position,classify,presentation
from ..game.engine import Game
from ..game.rewards import terminal_rewards,REWARD_VERSION
from ..game.rules import RULE_VERSION
from ..strategies.registry import create_strategy
from ..strategies.monte_carlo import MonteCarloRollout
from ..strategies.base import decide

KIND='middle_control_v1'

class MiddleConfig(StrictModel):
    name:str=Field(default='中間順位制御パイロット',min_length=1,max_length=100)
    deals:int=Field(default=1,strict=True,ge=1,le=4)
    start_offset:int=Field(default=7000,strict=True,ge=0,le=999900)
    turns:list[int]=Field(default=[0,6,11,12,13],min_length=1,max_length=5)
    trials:int=Field(default=8,strict=True,ge=2,le=64)
    validation_trials:int=Field(default=32,strict=True,ge=10,le=128)
    validation_offset:int=Field(default=7000,strict=True,ge=0,le=999900)
    max_validate:int=Field(default=2,strict=True,ge=0,le=3)
    continuation:tuple[str,str,str]=('Random','Random','Random')
    policy_seed:int=Field(default=42,strict=True,ge=0,le=999999)
    reproduce:bool=Field(default=True,strict=True)
    reproduce_rollouts:int=Field(default=2,strict=True,ge=1,le=8)
    timeout_seconds:int=Field(default=120,strict=True,ge=1,le=120)
    hypothesis:str=Field(default='目先の中間確率と終局価値の逆転、および相手得点差の変化を探索する。仮説は未検証。',min_length=1,max_length=2000)

    @model_validator(mode='after')
    def valid(self):
        if any(type(t) is not int or not 0<=t<15 for t in self.turns) or self.turns!=sorted(set(self.turns)):raise ValueError('手番は0〜14の昇順・重複なし')
        if any(n not in LIGHT for n in self.continuation):raise ValueError('継続戦略は軽量な登録戦略だけ')
        if middle_estimate(self)['derived_games_upper']>10000:raise ValueError('派生対局上限10000以内にしてください')
        return self


def middle_estimate(c):
    search=c.deals*sum(17-t for t in c.turns)*c.trials
    validation=c.max_validate*2*c.validation_trials
    reproduction=c.deals*6*3 if c.reproduce else 0
    nested=c.deals*6*(3+1+1)*(5+4+3)*c.reproduce_rollouts if c.reproduce else 0
    return {'independent_deals':c.deals,'positions':c.deals*len(c.turns),'search_derived_games':search,'validation_upper':validation,'reproduction_games':reproduction,
        'derived_games_upper':search+validation+nested,'estimated_seconds_range':[(search+validation+nested)*.001,(search+validation+nested)*.02],
        'note':'6役割順・条件・仮想世界を独立配札として数えない。時間は未校正の概算。'}


def reproduce(c,check,progress):
    rows=[]
    for deal_seed in range(c.start_offset,c.start_offset+c.deals):
        for condition,opponents in [('Random近似',None),('Heuristic',('Heuristic','Heuristic')),('Greedy / ScoreAware',('Greedy','ScoreAware'))]:
            for rotation,roles in enumerate(ROTATIONS):
                check();game=Game(deal_seed);p=roles.index(0)
                rngs=[Random(derived_seed(c.policy_seed,f'reproduction:{rotation}:{role}')) for role in roles]
                for _ in range(12):game.play(tuple(create_strategy('Random').choose(game.observe(i),rngs[i]).card for i in range(3)))
                initial=game.observe(p).game_scores;rank=rank_slots(initial,p)[-1];others=[initial[i] for i in range(3) if i!=p]
                policies=[MonteCarloRollout(c.reproduce_rollouts) if role==0 or opponents is None else create_strategy(opponents[role-1]) for role in roles]
                while not game.finished:
                    check();actions=[decide(policies[i],game.observe(i),rngs[i]).card for i in range(3)];check();game.play(tuple(actions))
                winners=game.winners
                rows.append({'deal_id':str(deal_seed),'condition':condition,'rotation':rotation,'target_seat':p,'start_scores':list(initial),'paper_rank':rank,'rank_slots':rank_slots(initial,p),
                    'gap_high':max(others)-initial[p],'gap_low':initial[p]-min(others),'reward':terminal_rewards(winners)[p],'sole_win':winners==(p,),'win':p in winners})
                progress()
    groups=[]
    for condition in sorted({r['condition'] for r in rows}):
        for rank in (1,2,3):
            subset=[r for r in rows if r['condition']==condition and r['paper_rank']==rank];by=defaultdict(list)
            for r in subset:by[r['deal_id']].append(r)
            groups.append({'condition':condition,'rank':rank,'games':len(subset),'independent_deals':len(by),'average_reward':float(np.mean([np.mean([r['reward'] for r in group]) for group in by.values()])) if by else None,
                'sole_win_rate':float(np.mean([np.mean([r['sole_win'] for r in group]) for group in by.values()])) if by else None,
                'win_rate':float(np.mean([np.mean([r['win'] for r in group]) for group in by.values()])) if by else None})
    return {'rows':rows,'groups':groups,'method':'近似再現：1–4ラウンドは全席Random。最終ラウンドの探索席はMonte Carlo Rollout、内部は全席Random継続仮定。全幅探索ではない。Random条件は3席探索、他条件は対象席だけ探索。',
        'paper_values':{'1':-.56,'2':.91,'3':-.54},'paper_source':'副田・田中2003 紙面33 §4.1–4.2、34 表5。同点は低い側の順位。元実験1000ゲーム、全幅探索。'}


class MiddleJobs:
    def __init__(self,store,design,evidence):
        self.store,self.design,self.evidence=store,design,evidence;self.lock=Lock();self.active=None;self.stop=Event();self.owned=set()
        with closing(sqlite3.connect(store.path)) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS middle_seed_reservations(seed INTEGER PRIMARY KEY,job_id TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS middle_evidence_links(series_id TEXT,version INTEGER,job_id TEXT,condition_hash TEXT,note TEXT,PRIMARY KEY(series_id,version,job_id))')

    def register(self,c):
        if middle_estimate(c)['estimated_seconds_range'][1]>c.timeout_seconds:raise ValueError('未校正の上側時間見積もりが時間予算を超えます。規模を縮小してください')
        snapshot={'config':c.model_dump(mode='json'),'sources':runtime_info()['source_sha256'],'rule':RULE_VERSION,'reward':REWARD_VERSION,'metric':'terminal_reward','created_at':now(),
            'seed_partition':'development','validation_partition':'validation-world-samples','hypothesis':c.hypothesis,'rotations':'all-six','sampler':'uniform-unseen-v1','comparison_family':'探索は全収集局面×(17候補の報酬＋136ペア×3指標)を上限としてBonferroni。検証は固定検証件数×5指標。','statistical_scope':'探索的。独立検証も同一局面条件付き世界の再評価で、実配札の一般化ではない。'}
        seeds=set(range(c.start_offset,c.start_offset+c.deals))|{1000000+c.validation_offset}
        with self.lock,closing(sqlite3.connect(self.store.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            for p, in db.execute('SELECT payload FROM experiments'):
                data=json.loads(p)
                if seeds&set(data.get('config',{}).get('deal_seeds',[])):raise ValueError('開発配札は使用済み')
            if any(db.execute('SELECT 1 FROM design_seeds WHERE seed=?',(s,)).fetchone() for s in seeds):raise ValueError('配札は既存Planで予約済み')
            if any(db.execute('SELECT 1 FROM middle_seed_reservations WHERE seed=?',(s,)).fetchone() for s in seeds):raise ValueError('配札・検証系列は予約済み')
            from uuid import uuid4
            identifier=str(uuid4());value={'experiment_kind':KIND,'status':'Registered','config':c.model_dump(mode='json'),'snapshot':snapshot,'condition_hash':digest(snapshot),'estimate':middle_estimate(c),'created_at':now(),'positions':[],'reproduction':None,'progress':0,'elapsed_seconds':0,'error':None}
            db.execute('INSERT INTO experiments VALUES (?,?)',(identifier,json.dumps(value)));db.executemany('INSERT INTO middle_seed_reservations VALUES (?,?)',[(s,identifier) for s in seeds])
        return self.get(identifier)

    def get(self,identifier):
        v=self.store.get(identifier)
        if not v or v.get('experiment_kind')!=KIND:raise KeyError(identifier)
        if digest(v['snapshot'])!=v['condition_hash'] or v['config']!=v['snapshot']['config']:v['status']='Invalidated'
        if v.get('result_hash') and digest({'positions':v['positions'],'reproduction':v['reproduction']})!=v['result_hash']:v['status']='Invalidated'
        if v['status']=='Running' and identifier not in self.owned:v['status']='Interrupted'
        if v['status']=='Invalidated':
            return {**v,'id':identifier,'positions':[],'reproduction':None,'candidate_count':0,'recommendations':[{'action':'監査・再登録','reason':'登録条件または結果hashが不一致です。改変された結果を評価に使いません。'}]}
        v['stored_result_hash']=v.get('result_hash')
        v['positions']=presentation(v['positions'])
        if v.get('result_hash'):v['result_hash']=digest({'positions':v['positions'],'reproduction':v['reproduction']})
        v['evidence_schema']='conditional-world-v2'
        v['id']=identifier
        v['candidate_count']=sum(len(p['search']['reversals']) for p in v['positions'])
        validations=[p['validation'] for p in v['positions'] if p['validation']]
        middle=sum('中間得点' in p.get('labels',[]) for p in v['positions'])
        recommendations=[]
        if not v['positions'] or not v['candidate_count']:
            recommendations.append({'action':'局面サンプル追加','reason':'この範囲で候補がないか、まだ未評価。逆転の不存在を意味しません。'})
        elif validations and any(x['direction_repeated'] for x in validations):
            recommendations.append({'action':'継続戦略の変更・相手構成追加','reason':'独立世界でも点推定方向が残った候補があります。ただし区間と別配札での頑健性は未確定です。'})
        else:recommendations.append({'action':'局面サンプル追加・仮説の見直し','reason':'選んだペアは未検証または方向未再現。仮説全体の否定ではなく、候補選抜の不安定性を確認します。'})
        if middle<2:recommendations.append({'action':'得点差条件の精密化','reason':f'厳密な中間得点局面は{middle}件。次の計画では中間順位と得点差を収集条件として固定してください。'})
        v['recommendations']=recommendations
        return v

    def history(self):return [self.get(i) for i,p in self.store.iter_experiments() if p.get('experiment_kind')==KIND]

    def start(self,identifier,expected_hash):
        with self.lock:
            if self.active:raise RuntimeError('中間順位実験は1件ずつ')
            v=self.get(identifier)
            if v['status']!='Registered' or v['condition_hash']!=expected_hash:raise ValueError('登録状態・Hashが不一致')
            if v['snapshot']['sources']!=runtime_info()['source_sha256']:raise ValueError('登録後に実装が変わりました。別計画にしてください')
            c=MiddleConfig.model_validate(v['config']);v.pop('id',None);v.pop('candidate_count',None);v['status']='Running';self.store.update(identifier,v);self.active=identifier;self.owned.add(identifier);self.stop=Event()
        def worker():
            started=monotonic()
            def check():
                if self.stop.is_set():raise InterruptedError('Cancelled')
                if monotonic()-started>c.timeout_seconds:raise InterruptedError('TimedOut')
            def persist():v['elapsed_seconds']=monotonic()-started;self.store.update(identifier,v)
            def progress():v['progress']+=1;persist()
            try:
                if c.reproduce:v['reproduction']=reproduce(c,check,progress);persist()
                validation_used=0
                for seed in range(c.start_offset,c.start_offset+c.deals):
                    game=Game(seed);rngs=[Random(derived_seed(c.policy_seed,f'collection:{p}')) for p in range(3)]
                    for turn in range(15):
                        check()
                        if turn in c.turns:
                            obs=game.observe(0);pid=digest({'observation':asdict(obs),'rule':RULE_VERSION});cards=tuple(sorted(obs.legal_actions))
                            search=evaluate_position(obs,cards,c.continuation,c.trials,derived_seed(c.policy_seed,'discovery:'+pid),check,progress,comparisons=c.deals*len(c.turns)*(17+136*3))
                            item={'position_id':pid,'deal_id':str(seed),'observation':asdict(obs),'rounds_remaining':5-turn//3,'labels':classify(obs,search),'search':search,'validation':None}
                            # 選択規則は登録時固定：局面順、最初の逆転ペア。検証データを候補選択へ戻さない。
                            if search['reversals'] and validation_used<c.max_validate:
                                from ..game.cards import Card
                                pair=search['reversals'][0];chosen=tuple(Card(**pair[k]) for k in ('a','b'))
                                val=evaluate_position(obs,chosen,c.continuation,c.validation_trials,derived_seed(1000000+c.validation_offset,'validation:'+pid),check,progress,comparisons=max(1,c.max_validate*5))
                                a,b=val['candidates'];val['selected_pair']={'a':pair['a'],'b':pair['b']};val['direction_repeated']=a['immediate_middle']>b['immediate_middle'] and b['reward']>a['reward'];val['scope']='独立世界標本での方向再評価。新しい実配札や確証的な一般化ではない。'
                                item['validation']=val;validation_used+=1
                            v['positions'].append(item);persist()
                        game.play(tuple(create_strategy('Random').choose(game.observe(p),rngs[p]).card for p in range(3)))
                v['status']='Completed'
            except InterruptedError as e:v['status']=str(e)
            except Exception as e:v['status']='Failed';v['error']=f'{type(e).__name__}: {e}'
            finally:
                v['result_hash']=digest({'positions':v['positions'],'reproduction':v['reproduction']});persist()
                with self.lock:self.active=None
        Thread(target=worker,daemon=True,name='middle-control').start();return self.get(identifier)

    def cancel(self,identifier):
        with self.lock:
            v=self.get(identifier)
            if self.active==identifier:self.stop.set()
            elif v['status']=='Registered':v.pop('id',None);v.pop('candidate_count',None);v['status']='Cancelled';self.store.update(identifier,v)
        return self.get(identifier)

    def design_draft(self,identifier):
        v=self.get(identifier)
        if v['status']!='Completed':raise ValueError('完了結果だけ参照可能')
        spec=PlanSpec.model_validate({'plan_id':'middle-followup-'+identifier[:8],'created_at':now(),'reason':'中間順位局面の探索結果を参考とした別条件の継続戦略比較。逆転局面の再検証そのものではない。',
            'hypothesis':v['config']['hypothesis'],'references':[identifier],'evaluation':{'participants':['Greedy','Heuristic'],'opponents':[{'name':'Random / Heuristic','strategies':['Random','Heuristic']}],'deals':2,'start_offset':v['config']['start_offset']+100}})
        return self.design.draft(spec)

    def link_evidence(self,identifier,series_id,version):
        v=self.get(identifier)
        if v['status']!='Completed':raise ValueError('完了結果だけ参照可能')
        self.evidence.raw(series_id,version)
        with closing(sqlite3.connect(self.store.path)) as db,db:
            try:db.execute('INSERT INTO middle_evidence_links VALUES (?,?,?,?,?)',(series_id,version,identifier,v['condition_hash'],'異なる条件付き局面実験の参照のみ。Seriesの対応差・独立配札数へ合算しない。'))
            except sqlite3.IntegrityError:raise ValueError('参照は登録済み') from None
        return {'series_id':series_id,'version':version,'job_id':identifier,'aggregated':False}

    def close(self):
        self.stop.set()
        for _ in range(100):
            if self.active is None:break
            sleep(.05)
