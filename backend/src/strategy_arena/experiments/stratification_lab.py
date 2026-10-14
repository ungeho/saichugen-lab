"""Middle登録基盤を再利用する合法軌跡の層別収集。"""
from dataclasses import asdict
from threading import Thread,Event
from time import monotonic
from random import Random
from collections import Counter
from typing import Literal
from pydantic import Field,model_validator
from .middle_lab import MiddleJobs,MiddleConfig
from .middle_analysis import LIGHT
from .stratification_analysis import StrataDefinition,stratify,period,select_positions,evaluate_stratified,cluster_summary
from .evolution import digest
from .rollout_quality import runtime_info
from .runner import derived_seed
from .evidence_lab import deal_identity
from ..game.engine import Game
from ..game.rules import RULE_VERSION
from ..strategies.registry import create_strategy
from ..game.cards import Card

COLLECTORS=('Random','Heuristic','ScoreAware','Zigzag','Reverse Zigzag')

class StratificationConfig(MiddleConfig):
    name:str=Field(default='厳密中間・層別パイロット',min_length=1,max_length=100)
    deals:int=Field(default=4,strict=True,ge=1,le=8)
    start_offset:int=Field(default=9000,strict=True,ge=0,le=999900)
    validation_offset:int=Field(default=9000,strict=True,ge=0,le=999900)
    turns:list[int]=Field(default=[3,6,9,11,12,13,14],min_length=1,max_length=8)
    reproduce:Literal[False]=False
    collectors:list[Literal['Random','Heuristic','ScoreAware','Zigzag','Reverse Zigzag']]=Field(default=list(COLLECTORS),min_length=1,max_length=5)
    definition:StrataDefinition=Field(default_factory=StrataDefinition)
    max_positions:int=Field(default=12,strict=True,ge=1,le=24)
    controls:int=Field(default=2,strict=True,ge=0,le=6)
    hypothesis:str=Field(default='厳密中間の上下差の層で局所順位と終局価値、相手得点差、中間維持を別々に評価する。ケースBは未検証。',min_length=1,max_length=2000)

    @model_validator(mode='after')
    def valid(self):
        if len(set(self.collectors))!=len(self.collectors):raise ValueError('収集元が重複')
        if self.turns!=sorted(set(self.turns)) or any(type(t) is not int or not 0<=t<15 for t in self.turns):raise ValueError('手番は0〜14の重複しない昇順')
        if self.controls>=self.max_positions:raise ValueError('厳密中間の分析枠が必要')
        if any(n not in LIGHT for n in self.continuation):raise ValueError('軽量継続戦略だけ')
        if stratification_estimate(self)['derived_games_upper']>10000:raise ValueError('派生対局上限10000以内にしてください')
        return self


def stratification_estimate(c):
    upper=c.max_positions*17*c.trials+c.max_validate*2*c.validation_trials
    return {'independent_deals':c.deals,'collection_games':c.deals*len(c.collectors),'scanned_positions_upper':c.deals*len(c.collectors)*len(c.turns)*3,
        'analyzed_positions_upper':c.max_positions,'derived_games_upper':upper,'estimated_seconds_range':[upper*.001+c.deals*.05,upper*.02+c.deals*len(c.collectors)*.1],
        'note':'同一配札の5収集元・3席・複数時点は独立配札数を増やさない。上側時間は未校正。'}


def collect(c,check=lambda:None,progress=lambda:None):
    records={};observations={};sources=runtime_info()['source_sha256'];seen=0
    for seed in range(c.start_offset,c.start_offset+c.deals):
        dh=deal_identity(seed,sources)
        for source in c.collectors:
            game=Game(seed);policies=[create_strategy(source) for _ in range(3)];rngs=[Random(derived_seed(c.policy_seed,f'collection-v2:{source}:{p}')) for p in range(3)]
            for turn in range(15):
                check()
                if turn in c.turns:
                    for p in range(3):
                        obs=game.observe(p);oh=digest(asdict(obs));ph=digest({'observation_hash':oh,'rule':RULE_VERSION});seen+=1
                        origin={'deal_id':str(seed),'deal_hash':dh,'source':source,'player':p,'turn':turn}
                        if ph in records:records[ph]['origins'].append(origin);continue
                        records[ph]={'position_hash':ph,'observation_hash':oh,**origin,'origins':[origin],'stratum':stratify(obs.game_scores,p,c.definition),'period':period(turn),
                            'round':turn//3+1,'game_scores':list(obs.game_scores),'seed_partition':'development','reachable':'engine-legal-history-v1'}
                        observations[ph]=obs
                game.play(tuple(policies[p].choose(game.observe(p),rngs[p]).card for p in range(3)))
            progress()
    rows=list(records.values())
    return rows,observations,{'scanned':seen,'unique_positions':len(rows),'duplicates':seen-len(rows),'strict_middle':sum(r['stratum']['strict_middle'] for r in rows),
        'by_class':dict(Counter(r['stratum']['class'] for r in rows)),'by_relation':dict(Counter(r['stratum']['relation'] for r in rows if r['stratum']['strict_middle'])),
        'by_source':{s:sum(any(o['source']==s for o in r['origins']) for r in rows) for s in c.collectors},
        'by_gap_size':{k:sum(r['stratum'][k] for r in rows) for k in ('both_small','both_large','equal_gaps')},'by_period':dict(Counter(r['period'] for r in rows)),'independent_deals':c.deals}


class StratificationJobs(MiddleJobs):
    kind='middle_stratification_v1'
    estimate=staticmethod(stratification_estimate)
    config_type=StratificationConfig

    def registration_extras(self,c):
        return {'rotations':'all-three-observers-per-collector-trajectory','strata':c.definition.model_dump(),'collectors':c.collectors,'analysis_selection':'均衡・上側接近・下側接近を巡回、配札・収集元の分析数を均す。時点優先12,11,13,14,9,6,3。結果を見て選ばない。',
            'validation_selection':'分析順で最初の逆転ペアを上限件数まで固定。世界標本を分離。','comparison_family':'最大局面数×(17候補の報酬＋272方向付きペア×7指標)。検証は上限件数×16指標。',
            'G3':'次ラウンド開始境界で厳密中間である確率。最終ラウンドは終局境界。','mechanism_claim':'同時成立でも因果機序の支持とは呼ばない。'}

    def result_content(self,v):
        return {**super().result_content(v),'inventory':v.get('inventory',[]),'collection_summary':v.get('collection_summary'),'cluster_summary':v.get('cluster_summary')}

    def get(self,identifier):
        v=super().get(identifier)
        if v['status']=='Invalidated':v.update(inventory=[],collection_summary=None,cluster_summary=None)
        return v

    def position_results(self,c,records,observations,check,progress):
        selected=select_positions(records,c.max_positions,c.controls,c.turns);validated=0
        for record in selected:
            check();obs=observations[record['position_hash']];pid=record['position_hash']
            result=evaluate_stratified(obs,tuple(sorted(obs.legal_actions)),c.continuation,c.trials,derived_seed(c.policy_seed,'strata-discovery:'+pid),c.max_positions*(17+272*7),check,progress)
            item={**record,'position_id':pid,'observation':asdict(obs),'labels':['中間得点' if record['stratum']['strict_middle'] else record['stratum']['class'],record['stratum']['relation'] or 'control',record['source']],
                'rounds_remaining':5-obs.turn//3,'search':result,'validation':None}
            if result['reversals'] and validated<c.max_validate:
                pair=result['reversals'][0];cards=tuple(Card(**pair[k]) for k in ('a','b'))
                validation=evaluate_stratified(obs,cards,c.continuation,c.validation_trials,derived_seed(1000000+c.validation_offset,'strata-validation:'+pid),max(1,c.max_validate*16),check,progress)
                direct=next(x for x in validation['pairs'] if x['a']==pair['a'] and x['b']==pair['b'])
                validation.update(selected_pair={'a':pair['a'],'b':pair['b']},selected_result=direct,direction_repeated=direct['g']['G1'],
                    discovery_case_b=pair['case_b'],validation_case_b=direct['case_b'],case_b_repeated=pair['case_b'] and direct['case_b'],
                    other_opponents_reproduced=False,causal_mechanism_supported=False,scope='独立世界での方向再評価。新しい独立配札や因果機序の検証ではない。')
                item['validation']=validation;validated+=1
            yield item

    def summarize_positions(self,positions):return cluster_summary(positions)

    def start(self,identifier,expected_hash):
        with self.lock:
            if self.active:raise RuntimeError('層別実験は1件ずつ')
            v=self.get(identifier)
            if v['status']!='Registered' or v['condition_hash']!=expected_hash:raise ValueError('登録状態・Hash不一致')
            if v['snapshot']['sources']!=runtime_info()['source_sha256']:raise ValueError('登録後に実装が変わりました')
            c=self.config_type.model_validate(v['config']);v.pop('id',None);v['status']='Running';v['inventory']=[];v['collection_summary']=None;v['cluster_summary']=None;self.active=identifier;self.owned.add(identifier);self.stop=Event();self.store.update(identifier,v)
        def worker():
            started=monotonic()
            def check():
                if self.stop.is_set():raise InterruptedError('Cancelled')
                if monotonic()-started>c.timeout_seconds:raise InterruptedError('TimedOut')
            def persist():v['elapsed_seconds']=monotonic()-started;self.store.update(identifier,v)
            def progress():v['progress']+=1;persist()
            try:
                records,observations,summary=collect(c,check,progress);v['inventory']=records;v['collection_summary']=summary;persist()
                for item in self.position_results(c,records,observations,check,progress):
                    v['positions'].append(item);persist()
                v['cluster_summary']=self.summarize_positions(v['positions']);v['status']='Completed'
            except InterruptedError as e:v['status']=str(e)
            except Exception as e:v['status']='Failed';v['error']=f'{type(e).__name__}: {e}'
            finally:
                v['result_hash']=digest(self.result_content(v));persist()
                with self.lock:self.active=None
        Thread(target=worker,daemon=True,name='stratification').start();return self.get(identifier)
