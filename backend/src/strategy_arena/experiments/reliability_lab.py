"""既存結果の診断集団と新規配札集団を分離して登録・実行する。"""
from copy import deepcopy
from dataclasses import asdict
from random import Random
from typing import Literal
from pydantic import Field,model_validator
from .stratification_lab import StratificationConfig,StratificationJobs,collect
from .decision_analysis import decision_positions
from .evolution import digest
from .reliability_analysis import analyze_reliability,reliability_summary
from ..game.cards import Card
from ..game.observation import Observation,PublicTurn
from ..rollouts import sampled_game


class ReliabilityConfig(StratificationConfig):
    name:str=Field(default='意思決定信頼性・小規模診断',min_length=1,max_length=100)
    deals:int=Field(default=1,strict=True,ge=1,le=4)
    start_offset:int=Field(default=13000,strict=True,ge=0,le=999900)
    validation_offset:int=Field(default=13000,strict=True,ge=0,le=999900)
    turns:list[int]=Field(default=[11],min_length=1,max_length=3)
    controls:Literal[0]=0
    max_validate:Literal[0]=0
    max_positions:int=Field(default=2,strict=True,ge=1,le=4)
    budgets:list[Literal[16,32,64,128,256]]=Field(default=[16,32,64,128,256],min_length=1,max_length=5)
    repeats:int=Field(default=2,strict=True,ge=2,le=5)
    models:list[Literal['Random','Heuristic','ScoreAware']]=Field(default=['Random','Heuristic','ScoreAware'],min_length=1,max_length=3)
    evaluation_worlds:int=Field(default=64,strict=True,ge=16,le=256)
    safety_tolerance:float=Field(default=0,ge=0,le=.1,allow_inf_nan=False)
    diagnostic_source_id:str|None=Field(default=None,min_length=1,max_length=100)
    historical_limit:int=Field(default=1,strict=True,ge=0,le=2)
    hypothesis:str=Field(default='選択予算・乱数・継続モデル依存を別々に記述し、選択誤差・モデル不一致・小さな価値差を競合する未確定の説明として調べる。',min_length=1,max_length=2000)

    @model_validator(mode='after')
    def valid(self):
        super().valid()
        if self.budgets!=sorted(set(self.budgets)) or any(type(b) is not int for b in self.budgets):raise ValueError('予算は指定された整数の昇順・重複なし')
        if len(set(self.models))!=len(self.models):raise ValueError('モデル重複')
        if self.diagnostic_source_id and not 0<self.historical_limit<self.max_positions:raise ValueError('診断枠に加え新規局面枠を1以上残してください')
        if self.continuation!=('Random','Random','Random'):raise ValueError('継続はmodelsで指定します。互換用continuationは既定値に固定')
        return self


def restore_observation(value):
    return Observation(value['player'],tuple(Card(**c) for c in value['hand']),
        tuple(PublicTurn(h['index'],tuple(Card(**c) for c in h['cards']),h['winner'],tuple(h['round_scores']),tuple(h['game_scores'])) for h in value['history']),
        tuple(value['round_scores']),tuple(value['game_scores']),value['turn'],tuple(value['hand_sizes']))


def reliability_estimate(c,historical=None):
    unknown=historical is None and c.diagnostic_source_id is not None
    count=c.historical_limit if unknown else len(historical or ())
    historical_cards=17*count if unknown else sum(len(p['observation']['hand']) for p in historical or ())
    legal_upper=(c.max_positions-count)*(17-min(c.turns))+historical_cards
    upper=legal_upper*len(c.models)*(max(c.budgets)*c.repeats+c.evaluation_worlds)
    return {'independent_fresh_deals':c.deals,'diagnostic_positions':None if unknown else count,'diagnostic_positions_upper':count,'analyzed_positions_upper':c.max_positions,
        'collection_games':c.deals*len(c.collectors),'derived_games_upper':upper,
        'selection_games_upper':legal_upper*len(c.models)*max(c.budgets)*c.repeats,
        'evaluation_games_upper':legal_upper*len(c.models)*c.evaluation_worlds,
        'estimated_seconds_range':[upper*.0005,upper*.003+c.deals*len(c.collectors)*.1],
        'note':('CLI単独見積もりでは診断手札を17枚で保守的に仮定。登録時に実数を固定。' if unknown else '')+'ネストした予算を足し算しない。モデルごとの対局は実計算する。時間は未校正、120秒・80000派生対局が上限。'}


class ReliabilityJobs(StratificationJobs):
    kind='decision_reliability_v1'
    config_type=ReliabilityConfig
    progress_interval=.25

    def historical(self,c):
        if not c.diagnostic_source_id:return []
        source=self.store.get(c.diagnostic_source_id)
        if not source or source.get('experiment_kind')!='middle_decision_v1' or source.get('status')!='Completed':raise ValueError('完了したPhase 29結果が必要')
        if digest(source['snapshot'])!=source['condition_hash'] or source['config']!=source['snapshot']['config'] or digest(StratificationJobs.result_content(self,source))!=source.get('result_hash'):raise ValueError('診断元Hashが不一致')
        selected=[p for p in source['positions'] if any(f['rule']=='Terminal-Value' and f['observed'] for f in p['decision']['failures'])][:c.historical_limit]
        if not selected:raise ValueError('Terminal-Valueの劣後診断例がありません')
        output=[]
        for p in selected:
            obs=restore_observation(p['observation']);sampled_game(obs,Random(0))
            if digest(asdict(obs))!=p['observation_hash']:raise ValueError('診断観測Hashが不一致')
            keys=('position_hash','observation_hash','deal_hash','deal_id','source','player','turn','round','period','stratum','origins','game_scores','observation')
            output.append({**{k:deepcopy(p[k]) for k in keys},'population':'diagnostic','source_job_id':c.diagnostic_source_id,
                'source_condition_hash':source['condition_hash'],'source_result_hash':source['result_hash'],
                'selection_bias':'Phase 29の独立評価結果を見て選んだ劣後例。新規局面と統合しない。'})
        return output

    def estimate(self,c):return reliability_estimate(c,self.historical(c))

    def registration_extras(self,c):
        if self.estimate(c)['derived_games_upper']>80000:raise ValueError('80000派生対局以内にしてください')
        return {**super().registration_extras(c),'historical':self.historical(c),'reliability_version':'nested-model-sensitivity-v1',
            'analysis_selection':'診断元のTerminal劣後例を記録順で固定。新規局面は結果を見る前にPhase 29の層別巡回で選ぶ。',
            'validation_selection':'全合法手を別世界でモデル別に評価。全予算・選択反復はこの評価表を共有。',
            'comparison_family':'選択は局面×モデル×反復×予算×(17+272)。評価は局面×モデル×17×17。配札集約は10000対比上限。',
            'nesting':'同一モデル・反復内で最大予算の先頭を使う。反復間は別seed。モデル間は同じ世界seed、政策乱数にはモデル名・版が入る。',
            'regret':'同じ独立評価表の最大値を有限標本参照とする探索的Regret。参照選択と測定を分離していない。',
            'strata_bins':{'version':'reliability-bins-v1','max_immediate':[.25,.5,.75],'top_two_gap':[.1,.5]},
            'tie_break':'ランク昇順・同ランクはスート昇順。Safetyは中間率優先、許容幅内の条件付きmargin最大。',
            'causal_claim':'原因の識別・Winner’s Curse・真の最適手・ケースB機序は確証しない。'}

    def collect_positions(self,c,check,progress,snapshot):
        fresh,observations,summary=collect(c,check,progress)
        for p in fresh:p['population']='fresh'
        historical=deepcopy(snapshot['historical'])
        for p in historical:observations[p['position_hash']]=restore_observation(p['observation'])
        summary.update(diagnostic_positions=len(historical),diagnostic_deals=len({p['deal_hash'] for p in historical}),
            population_note='独立配札数は新規集団。診断集団は別の既存配札で、結果選抜済み。')
        return fresh+historical,observations,summary

    def position_results(self,c,records,observations,check,progress):
        historical=[r for r in records if r['population']=='diagnostic'];fresh=[r for r in records if r['population']=='fresh']
        selected=historical+decision_positions(fresh,c.max_positions-len(historical),0)
        for record in selected:
            check();pid=record['position_hash'];obs=observations[pid];result=analyze_reliability(obs,c,pid,check,progress)
            yield {**record,'position_id':pid,'observation':asdict(obs),'labels':['中間得点'] if record['stratum']['strict_middle'] else [],
                'search':{'reversals':[],'case_b_candidates':[]},'validation':None,'reliability':result}

    def summarize_positions(self,positions):return reliability_summary(positions)

    def get(self,identifier):
        v=super().get(identifier)
        if v['status']!='Invalidated':v['recommendations']=[{'action':'選択反復・新規配札・評価モデルを分けて追加する','reason':'選択不足、モデル依存、近接価値は同時にあり得る。少数の診断局面から原因を確定しない。'}]
        return v
