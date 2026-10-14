"""複数相手構成を固定してArenaを順に実行するEvaluation Lab。"""
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from threading import Event,Lock,Thread
from time import monotonic,sleep
from typing import Literal
import json
import numpy as np
from pydantic import BaseModel,ConfigDict,Field,model_validator
from .arena import ArenaRequest,ArenaPlan,arena_estimate,compare_arena
from .quality_statistics import complete_deals,paired_deal_differences
from .evaluation_statistics import PlanningInput,plan_samples,fixed_evidence,factorial_contrasts
from .evolution import digest
from ..strategies.declarative import StrategyDefinition,builtin_definitions

KIND='evaluation_lab_v1'
BASELINE='5004f667ade99183deb04745f9eabade38cc17a0'


class Opponents(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=80)
    strategies:tuple[str,str]


class EvaluationRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(default='固定標本評価',min_length=1,max_length=100)
    participants:list[str]=Field(min_length=2,max_length=6)
    opponents:list[Opponents]=Field(min_length=1,max_length=4)
    deals:int=Field(default=2,strict=True,ge=1,le=20)
    start_offset:int=Field(default=600,strict=True,ge=0,le=999900)
    seed_partition:Literal['development','validation']='development'
    policy_seed:int=Field(default=42,strict=True,ge=0,le=2**32-1)
    include_expensive:bool=Field(default=False,strict=True)
    timeout_seconds:int=Field(default=180,strict=True,ge=1,le=300)
    alpha:float=Field(default=.05,ge=.000001,le=.2,allow_inf_nan=False)
    minimum_effect:float=Field(default=.25,ge=.001,le=4,allow_inf_nan=False)
    power:float=Field(default=.8,gt=.5,lt=1,allow_inf_nan=False)
    max_deals:int=Field(default=1000,strict=True,ge=10,le=100000)
    weights:list[float]|None=Field(default=None,min_length=1,max_length=4)
    purpose:Literal['comparison','reserve_ablation','adaptive_ablation']='comparison'
    evolution_id:str|None=None
    evaluation_mode:Literal['fixed']='fixed'
    capture_rank_trace:bool=Field(default=False,strict=True)
    deal_layout:Literal['distinct','shared']='distinct'
    composition_deals:list[int]|None=Field(default=None,min_length=1,max_length=4)
    family_size:int|None=Field(default=None,strict=True,ge=1,le=100)

    @model_validator(mode='after')
    def valid(self):
        if len(set(self.participants))!=len(self.participants):raise ValueError('候補が重複しています')
        if len({o.name for o in self.opponents})!=len(self.opponents) or len({tuple(sorted(o.strategies)) for o in self.opponents})!=len(self.opponents):raise ValueError('相手構成が重複しています')
        if self.weights is not None and (len(self.weights)!=len(self.opponents) or any(not np.isfinite(w) or w<=0 for w in self.weights) or abs(sum(self.weights)-1)>1e-8):raise ValueError('統合重みは構成ごとに正で合計1にしてください')
        if self.purpose!='comparison' and self.participants!=ablation_references(self.purpose):raise ValueError('Ablationは固定した00・10・01・11の4条件が必要です')
        if self.composition_deals is not None and (len(self.composition_deals)!=len(self.opponents) or any(type(n) is not int or not 1<=n<=20 for n in self.composition_deals)):raise ValueError('構成別配札数は各1〜20件で構成数と一致させてください')
        if self.weights is not None and len(set(self.counts))!=1:raise ValueError('重み付きブロック統合には同じ配札数が必要です')
        base=len(self.opponents)*(len(self.participants)-1+(self.purpose!='comparison'))
        if self.weights is not None:base+=len(self.participants)-1+(self.purpose!='comparison')
        if self.family_size is not None and self.family_size<base:raise ValueError('多重比較数を実際の比較集合より小さくできません')
        return self

    @property
    def counts(self):return self.composition_deals or [self.deals]*len(self.opponents)

    def plans(self,definitions):
        plans=[ArenaRequest(participants=self.participants,opponents=o.strategies,deals=self.counts[i],
            start_offset=self.start_offset+(0 if self.deal_layout=='shared' else sum(self.counts[:i])),seed_partition=self.seed_partition,policy_seed=self.policy_seed,
            include_expensive=self.include_expensive,timeout_seconds=self.timeout_seconds,capture_rank_trace=self.capture_rank_trace).resolve(definitions) for i,o in enumerate(self.opponents)]
        estimates=[arena_estimate(p) for p in plans]
        if sum(e['games'] for e in estimates)>360 or sum(e['rollout_upper_bound'] for e in estimates)>250000:raise ValueError('全構成合計で360対局・25万Rollout以内へ分割してください')
        return plans


def ablation_definitions(purpose):
    family='codex_reserve' if purpose=='reserve_ablation' else 'codex_adaptive_theorist'
    if purpose not in ('reserve_ablation','adaptive_ablation'):raise ValueError('未知のAblationです')
    parent=next(d for d in builtin_definitions() if d.id==family)
    proposal=Path(__file__).resolve().parents[4]/'experiments'/'evolution-candidates'/f'{family}.json'
    both=StrategyDefinition.model_validate(json.loads(proposal.read_text(encoding='utf-8'))['definition'])
    children=[]
    for index in (0,1):
        data=parent.model_dump(mode='json',exclude={'definition_hash'})
        data.update(version=f'1.0.{20+index}',creator='Codex / Phase23 Ablation',created_at=both.created_at.isoformat(),
            parent=both.parent.model_dump(),name=parent.name+(' / 要因Aのみ' if index==0 else ' / 要因Bのみ'),
            hypothesis='親からの変更の単独寄与を比較する未検証仮説',change_summary='温存のみ' if purpose=='reserve_ablation' and index==0 else 'ラウンドのみ' if purpose=='reserve_ablation' else '序盤のみ' if index==0 else '上位時のみ',change_reason='Phase 22の複合変更を2×2要因計画で分離するため')
        if purpose=='reserve_ablation':
            for spec in data['theory_config']['theories']:
                if (spec['id'].startswith('reserve_'))==(index==0):spec['weight']=next(s.weight for s in both.theory_config.theories if s.id==spec['id'])
        else:
            rule=1 if index==0 else 0
            data['rules'][rule]=both.rules[rule].model_dump()
        children.append(StrategyDefinition.model_validate(data))
    return parent,children[0],children[1],both


def ablation_references(purpose):return [d.reference for d in ablation_definitions(purpose)]


def estimate_evaluation(request,definitions):
    plans=request.plans(definitions);estimates=[arena_estimate(p) for p in plans]
    return {'games':sum(e['games'] for e in estimates),'independent_deals_per_composition':request.counts,
            'distinct_deals':max(request.counts) if request.deal_layout=='shared' else sum(request.counts),'rollout_upper_bound':sum(e['rollout_upper_bound'] for e in estimates),
            'estimated_seconds_range':[sum(e['estimated_seconds_range'][i] for e in estimates) for i in (0,1)],
            'note':'相手構成は別々に集計。全6席順は独立標本ではありません。時間は未校正の概算です。'}


def analyze_arena(record,request, *, fixed_complete=False,confirmatory=False):
    config=ArenaPlan.model_validate(record['config']);settings=config.settings
    clusters=[complete_deals(config,record['results'],s) for s in settings]
    m=len(request.opponents)*(len(settings)-1+(1 if request.purpose!='comparison' else 0))
    if request.weights is not None:m+=len(settings)-1+(1 if request.purpose!='comparison' else 0)
    m=request.family_size or m
    seconds=record['elapsed_seconds']/len(config.deal_seeds) if config.deal_seeds and record['elapsed_seconds']>0 else None
    comparisons=[];samples=[]
    for i,setting in enumerate(settings[1:],1):
        match=compare_arena(record,record,settings[0].identifier,setting.identifier)
        differences=paired_deal_differences(clusters[0],clusters[i]) if match['comparable'] else {}
        evidence=fixed_evidence(differences.values(),alpha=request.alpha,comparisons=m,completed=fixed_complete,confirmatory=confirmatory)
        planning=plan_samples(PlanningInput(observed_deals=len(differences),mean_difference=evidence['mean'],sd_difference=evidence['sd'],
            minimum_effect=request.minimum_effect,alpha=request.alpha,power=request.power,max_deals=request.max_deals,comparisons=m,seconds_per_deal=seconds))
        comparisons.append({'strategy_a':settings[0].reference,'strategy_b':setting.reference,'matching':match,'fixed_evidence':evidence,'planning':planning})
        samples.append(differences)
    ablation=None
    if request.purpose!='comparison' and all(c['matching']['comparable'] for c in comparisons):
        common=sorted(set.intersection(*(set(c) for c in clusters)))
        cells=[[float(np.mean([r['terminal_rewards'][r['seat']] for r in group[deal]])) for deal in common] for group in clusters]
        contrasts=factorial_contrasts(cells)
        ablation={key:fixed_evidence(values,alpha=request.alpha,comparisons=m,completed=fixed_complete,confirmatory=confirmatory,bound=8 if key=='interaction' else 4) for key,values in contrasts.items()}
    strength=record['summary']['settings'];efficiency=[]
    for comparison,setting in zip(comparisons,strength[1:]):
        a,b=strength[0]['decision_ms']['mean'],setting['decision_ms']['mean']
        extra=b-a if a is not None and b is not None else None
        difference=comparison['fixed_evidence']['mean']
        efficiency.append({'strategy_b':setting['reference'],'added_decision_ms':extra,
            'paired_reward_gain_per_added_ms':difference/extra if difference is not None and extra is not None and extra>0 else None,
            'note':'同条件の対応差÷追加判断ms。追加コストが0以下または比較不能なら未定義。総合点や順位ではない。'})
    return {'comparisons':comparisons,'ablation':ablation,'samples':samples,'comparison_family_size':m,'seconds_per_deal':seconds,
            'strength':strength,'efficiency':efficiency,'seed_partition':request.seed_partition,'fixed_complete':fixed_complete}


class EvaluationJobs:
    def __init__(self,store,definitions,arena,evolution):
        self.store,self.definitions,self.arena,self.evolution=store,definitions,arena,evolution
        self.lock=Lock();self.active=None;self.cancel_event=None;self.current=None;self.owned=set();self.closed=False

    def submit(self,request):
        plans=request.plans(self.definitions)
        with self.lock:
            if self.closed or self.active is not None:raise RuntimeError('Evaluation Labは1件ずつ実行してください')
            with self.arena.lock:
                if self.arena.active is not None:raise RuntimeError('Arena/Evolutionの評価完了を待ってください')
            if request.evolution_id:
                raw,_=self.evolution.raw(request.evolution_id)
                parent=raw['parent'];refs=[parent['id']+'@'+parent['version'],*[c['id']+'@'+c['version'] for c in raw['children']]]
                if request.participants[0]!=refs[0] or not set(request.participants)<=set(refs):raise ValueError('Evolutionの固定した親子と一致しません')
            known=set()
            used_seeds=set()
            for _,p in self.store.iter_experiments():
                c=p.get('config',{})
                if c.get('opponent_entries'):known.add(tuple(sorted(e['reference'] for e in c['opponent_entries'])))
                used_seeds.update(c.get('deal_seeds',[]))
            payload={'experiment_kind':KIND,'schema_version':1,'baseline_commit':BASELINE,'config':request.model_dump(mode='json'),
                'plans':[p.model_dump(mode='json') for p in plans],'status':'running','jobs':[], 'error':None,'elapsed_seconds':0,
                'created_at':datetime.now(timezone.utc).isoformat(),'estimate':estimate_evaluation(request,self.definitions),
                'opponent_novelty':[tuple(sorted(o.strategies)) not in known for o in request.opponents],
                'fresh_deals':[not bool(set(p.deal_seeds)&used_seeds) for p in plans],
                'candidate_count':len(request.participants)-1,'selection_history':[{'evolution_id':request.evolution_id,'participants':request.participants,'fixed_before_execution':True}]}
            payload['config_hash']=digest({'config':payload['config'],'plans':payload['plans'],'baseline':BASELINE})
            identifier=self.store.save(payload);self.active=identifier;self.owned.add(identifier);stop=self.cancel_event=Event()
        if request.evolution_id:self.evolution.event(request.evolution_id,{'type':'evaluation_lab_started','evaluation_id':identifier,'candidate_count':payload['candidate_count'],'config_hash':payload['config_hash']})
        def worker():
            start=monotonic()
            def persist():
                payload['elapsed_seconds']=monotonic()-start;self.store.update(identifier,payload)
            try:
                for index,plan in enumerate(plans):
                    if stop.is_set():payload['status']='cancelled';break
                    job=self.arena.submit(plan);self.current=job['id'];payload['jobs'].append({'composition':index,'arena_id':job['id']});persist()
                    while True:
                        if stop.is_set():self.arena.cancel(job['id'])
                        job=self.arena.get(job['id'])
                        if job['status'] not in ('running','cancelling'):break
                        sleep(.1)
                    persist()
                    if job['status']!='completed':payload['status']=job['status'];break
                else:payload['status']='cancelled' if stop.is_set() else 'completed'
            except Exception as error:
                payload['status']='failed';payload['error']=f'評価に失敗しました ({type(error).__name__})'
            finally:
                persist()
                with self.lock:self.active=None;self.current=None;self.cancel_event=None
        Thread(target=worker,daemon=True,name='evaluation-lab').start()
        return self.get(identifier)

    def get(self,identifier):
        payload=self.store.get(identifier)
        if not payload or payload.get('experiment_kind')!=KIND:raise KeyError(identifier)
        if payload['status']=='running' and identifier not in self.owned:payload['status']='interrupted'
        request=EvaluationRequest.model_validate(payload['config']);reports=[]
        for job in payload['jobs']:
            record=self.arena.get(job['arena_id'],True);index=job['composition']
            complete=payload['status']=='completed' and record['status']=='completed' and all(s['independent_deals']==request.counts[index] for s in record['summary']['settings'])
            reports.append({'composition':index,'name':request.opponents[index].name,'arena_id':job['arena_id'],'status':record['status'],
                'completed_games':record['completed_games'],'elapsed_seconds':record['elapsed_seconds'],'report':analyze_arena(record,request,fixed_complete=complete,confirmatory=request.seed_partition=='validation' and payload['fresh_deals'][index])})
        integrated=None
        if request.weights is not None and len(reports)==len(request.opponents):
            integrated=[]
            for i in range(len(request.participants)-1):
                # 文字列seedの辞書順ではなく、計画の配札番号でブロックを揃える。
                # 同じ方策rng番号を別ブロックへ分散させない。
                samples=[[r['report']['samples'][i].get(str(seed)) for seed in payload['plans'][r['composition']]['deal_seeds']] for r in reports]
                aligned=all(all(v is not None for v in s) for s in samples)
                values=[sum(w*s[j] for w,s in zip(request.weights,samples)) for j in range(len(samples[0]))] if aligned else []
                integrated.append({'strategy_b':request.participants[i+1],'weights':request.weights,'unit':'各構成から1配札ずつ組にした独立ブロック。総配札数と異なる。',
                    'evidence':fixed_evidence(values,alpha=request.alpha,comparisons=reports[0]['report']['comparison_family_size'],completed=payload['status']=='completed' and aligned,confirmatory=request.seed_partition=='validation' and all(payload['fresh_deals']))})
        recommendations=[]
        for report in reports:
            for c in report['report']['comparisons']:
                plan=c['planning'];e=c['fixed_evidence']
                recommendations.append({'reason':plan['reason'],'observations':{'independent_deals':e['independent_deals'],'difference':e['mean'],'sd':e['sd']},
                    'proposal':{'opponents':request.opponents[report['composition']].model_dump(),'seed_partition':'development','additional_deals':plan.get('pilot_additional',plan.get('estimated_additional')),'new_unused_offset_required':True},
                    'estimated_seconds':plan.get('pilot_seconds',plan.get('estimated_seconds')),'limitation':plan['uncertainty']})
                # 自動実行しない、新しい開発用パイロットの完全な設定。
                # 旧2件と新8件を確証標本へ継ぎ足す設定にはしない。
                offset=request.start_offset+len(request.opponents)*request.deals+100
                next_request=request.model_copy(update={'name':request.name[:70]+' / 次の開発パイロット',
                    'opponents':[request.opponents[report['composition']]],'deals':10,'start_offset':offset,
                    'seed_partition':'development','weights':None,'evolution_id':None,'composition_deals':None,'family_size':None})
                if offset<=999900:
                    recommendations[-1]['execution_request']=next_request.model_dump(mode='json')
                    recommendations[-1]['execution_estimated_seconds']=report['report']['seconds_per_deal']*10 if report['report']['seconds_per_deal'] else None
                    recommendations[-1]['limitation']+=' 実行設定は別の固定10配札パイロットです。offsetの未使用確認と再見積もりが必要です。'
        if len(request.opponents)==1:recommendations.append({'reason':'相手構成が1種類だけです','observations':{'compositions':1},'proposal':{'opponents':'別の未使用構成を事前固定','seed_partition':'development'},'estimated_seconds':payload['elapsed_seconds'] or None,'limitation':'未知の相手への汎化を確認したとは言えません'})
        if request.purpose=='comparison' and request.evolution_id:recommendations.append({'reason':'改良項目の単独寄与は未分離です','observations':{'candidate_count':payload['candidate_count']},'proposal':{'purpose':'2×2 Ablation','seed_partition':'development'},'estimated_seconds':payload['elapsed_seconds']*2 or None,'limitation':'時間は設定数を倍にした粗い概算'})
        return {'id':identifier,**payload,'reports':reports,'integrated':integrated,'recommendations':recommendations,
                'completed_games':sum(r['completed_games'] for r in reports),
                'robustness':{'between_composition_reward_range':{ref:[min(v),max(v)] for ref in request.participants if (v:=[s['average_terminal_reward'] for r in reports for s in r['report']['strength'] if s['reference']==ref and s['average_terminal_reward'] is not None])},
                    'note':'相手別の点推定の範囲。汎用性の証明ではない。未使用相手はこのDBの記録範囲で判断。'}}

    def history(self):return [{'id':i,'name':p['config']['name'],'status':self.get(i)['status']} for i,p in self.store.iter_experiments() if p.get('experiment_kind')==KIND]
    def cancel(self,identifier):
        self.get(identifier)
        with self.lock:
            if self.active==identifier:self.cancel_event.set()
        return self.get(identifier)
    def close(self):
        with self.lock:
            self.closed=True
            if self.cancel_event:self.cancel_event.set()
