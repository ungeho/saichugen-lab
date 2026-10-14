"""追記型の実験計画。登録・実行・判定を別操作にする。"""
from contextlib import closing
from datetime import datetime,timezone
from itertools import combinations
from threading import RLock,Thread
from time import monotonic,sleep
from typing import Literal
import json
import sqlite3
import numpy as np
from pydantic import BaseModel,ConfigDict,Field,model_validator
from .evaluation_lab import EvaluationRequest,estimate_evaluation,ablation_definitions
from .evaluation_statistics import PlanningInput,plan_samples,fixed_evidence
from .evolution import digest
from .rollout_quality import runtime_info
from ..game.rules import RULE_VERSION
from ..game.rewards import REWARD_VERSION

BASELINE='6aafbd0a8860f5832bca42de0989f7793a032109'


def now():return datetime.now(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config=ConfigDict(extra='forbid')


class Budget(StrictModel):
    max_independent_deals:int=Field(default=20,strict=True,ge=1,le=80)
    max_games:int=Field(default=360,strict=True,ge=1,le=360)
    max_rollouts:int=Field(default=250000,strict=True,ge=0,le=250000)
    allowed_seconds:int=Field(default=120,strict=True,ge=1,le=300)
    measured_seconds_per_deal_composition:float|None=Field(default=None,gt=0,le=10000,allow_inf_nan=False)


class Statistics(StrictModel):
    method:Literal['fixed_hoeffding']='fixed_hoeffding'
    correction:Literal['bonferroni']='bonferroni'
    null:Literal['contrast_mean=0']='contrast_mean=0'
    alternative:Literal['contrast_mean!=0']='contrast_mean!=0'
    metric:Literal['terminal_reward']='terminal_reward'
    aggregation:Literal['deal_mean_all_6']='deal_mean_all_6'
    stop:Literal['fixed_n_or_budget_or_user_cancel']='fixed_n_or_budget_or_user_cancel'
    time_handling:Literal['diagnostic_and_budget']='diagnostic_and_budget'
    decision_threshold:float=Field(default=0,ge=0,le=4,allow_inf_nan=False)
    max_decision_time_ratio:float=Field(default=2,ge=1,le=100,allow_inf_nan=False)


class PlanSpec(StrictModel):
    plan_id:str=Field(pattern=r'^[a-z][a-z0-9_-]{2,79}$')
    version:int=Field(default=1,strict=True,ge=1,le=100000)
    parent_version:int|None=Field(default=None,strict=True,ge=1)
    created_at:datetime
    reason:str=Field(min_length=1,max_length=2000)
    hypothesis:str=Field(min_length=1,max_length=3000)
    interpretation:Literal['exploratory','confirmatory']='exploratory'
    references:list[str]=Field(default_factory=list,max_length=20)
    pilot_in_confirmatory:Literal['excluded']='excluded'
    evaluation:EvaluationRequest
    between_opponents:bool=Field(default=True,strict=True)
    statistics:Statistics=Field(default_factory=Statistics)
    budget:Budget=Field(default_factory=Budget)

    @model_validator(mode='after')
    def valid(self):
        if self.created_at.tzinfo is None:raise ValueError('作成日時にタイムゾーンが必要です')
        self.created_at=self.created_at.astimezone(timezone.utc)
        if self.parent_version is not None and self.parent_version>=self.version:raise ValueError('派生元は前の版で指定してください')
        if self.interpretation=='confirmatory' and self.evaluation.seed_partition!='validation':raise ValueError('確証的評価は未使用の検証用配札で行ってください')
        if self.interpretation=='exploratory' and self.evaluation.seed_partition!='development':raise ValueError('パイロットは開発用配札にしてください')
        if self.between_opponents and len(self.evaluation.opponents)>1 and self.evaluation.deal_layout!='shared':raise ValueError('構成間の対応効果差には共通配札が必要です')
        if len(set(self.references))!=len(self.references):raise ValueError('参照実験IDが重複しています')
        return self


def family(request,between):
    members=[]
    for i in range(len(request.opponents)):
        members.extend(f'effect:{i}:{j}' for j in range(1,len(request.participants)))
        if request.purpose!='comparison':members.append(f'ablation_interaction:{i}')
    if request.weights is not None:
        members.extend(f'integrated:{j}' for j in range(1,len(request.participants)))
        if request.purpose!='comparison':members.append('integrated_interaction_reserved')
    if between:
        for a,b in combinations(range(len(request.opponents)),2):
            members.extend(f'between:{a}:{b}:{j}' for j in range(1,len(request.participants)))
    return members


def opponent_effect_difference(first,second):
    """同じ配札の (B−A)相手2 − (B−A)相手1。二重計上しない。"""
    return {key:second[key]-first[key] for key in sorted(first.keys()&second.keys(),key=int)}


class DesignPlanningInput(PlanningInput):
    mean_difference:float|None=Field(default=None,ge=-8,le=8,allow_inf_nan=False)
    sd_difference:float|None=Field(default=None,ge=0,le=16,allow_inf_nan=False)
    max_deals:int=Field(default=1000,strict=True,ge=1,le=100000)
    max_games:int=Field(default=360,strict=True,ge=1,le=360)
    contrast_bound:Literal[4,8]=4
    opponent_count:int=Field(default=2,strict=True,ge=1,le=4)
    setting_count:int=Field(default=2,strict=True,ge=2,le=6)
    rotations:Literal[6]=6
    shared_deals:bool=Field(default=True,strict=True)
    allowed_seconds:float=Field(default=120,gt=0,le=100000,allow_inf_nan=False)


def design_sample_plan(request):
    result=plan_samples(request,bound=request.contrast_bound)
    def cost(n):
        if n is None:return None
        seconds=n*request.opponent_count*request.seconds_per_deal if request.seconds_per_deal else None
        distinct=n if request.shared_deals else n*request.opponent_count;games=n*request.opponent_count*request.setting_count*6
        return {'deals_per_composition':n,'distinct_deals':distinct,'games':games,'seconds':seconds,
                'within_deal_budget':distinct<=request.max_deals,'within_game_budget':games<=request.max_games,
                'within_time_budget':seconds<=request.allowed_seconds if seconds is not None else None}
    return {**result,'normal_cost':cost(result['estimated_total']),'bounded_cost':cost(result['conservative_total']),
            'pilot_cost':cost(max(10,request.observed_deals+result.get('pilot_additional',0))) if result['status']=='pilot_required' else None,
            'time_unit':'seconds_per_dealは1構成・全設定・6席順の実測秒。共有配札でも計算は構成数倍。'}


class AllocationItem(StrictModel):
    name:str=Field(min_length=1,max_length=80)
    priority:int=Field(default=1,strict=True,ge=1,le=5)
    untested:bool=Field(default=True,strict=True)
    observed_deals:int=Field(default=0,strict=True,ge=0,le=100000)
    sd:float|None=Field(default=None,ge=0,le=8,allow_inf_nan=False)
    minimum_effect:float=Field(default=.5,ge=.001,le=4,allow_inf_nan=False)
    seconds_per_deal:float=Field(default=1,gt=0,le=100000,allow_inf_nan=False)


class AllocationRequest(StrictModel):
    items:list[AllocationItem]=Field(min_length=1,max_length=4)
    allowed_seconds:float=Field(default=60,gt=0,le=300,allow_inf_nan=False)
    max_deals:int=Field(default=20,strict=True,ge=1,le=80)


def allocate(request):
    if len({i.name for i in request.items})!=len(request.items):raise ValueError('配分項目名が重複しています')
    counts=[0]*len(request.items);remaining=request.allowed_seconds
    scores=[i.priority*(2 if i.untested else 1)*max(1,10-i.observed_deals)*
            (max(1,(i.sd/i.minimum_effect)**2) if i.observed_deals>=10 and i.sd else 1)/i.seconds_per_deal for i in request.items]
    for _ in range(request.max_deals):
        eligible=[j for j,i in enumerate(request.items) if counts[j]<20 and i.seconds_per_deal<=remaining+1e-10]
        if not eligible:break
        chosen=min(eligible,key=lambda j:(-scores[j]/(counts[j]+1),request.items[j].name))
        counts[chosen]+=1;remaining-=request.items[chosen].seconds_per_deal
    total=sum(counts)
    return {'allocation':[{'name':i.name,'deals':n,'ratio':n/total if total else 0,'priority_score':s} for i,n,s in zip(request.items,counts,scores)],
            'estimated_seconds':request.allowed_seconds-remaining,'remaining_seconds':max(0,remaining),
            'reason':'優先度・未検証・配札不足・十分な標本の分散/改善幅・時間から決定的に配分。登録前に固定し、実行中は変更しない。',
            'limitation':'配分比率はサンプリング比率であり、相手母集団の統合重みではない。推定コストに基づく設計。'}


def pilot_template():
    return PlanSpec(plan_id='adaptive-b-opponent-pilot',created_at=datetime.now(timezone.utc),
        reason='Phase 23の2配札ではB単独変更の効果の符号が相手構成で逆転した。相性差の証拠ではないため追試する。',
        hypothesis='局面切替系B単独変更の効果はRandom/HeuristicとGreedy/ScoreAwareで異なる可能性がある。',
        evaluation=EvaluationRequest(name='局面切替B単独・共通配札パイロット',participants=['codex_adaptive_theorist@1.0.0','codex_adaptive_theorist@1.0.21'],
            opponents=[{'name':'Random / Heuristic','strategies':['Random','Heuristic']},{'name':'Greedy / ScoreAware','strategies':['Greedy','ScoreAware']}],
            deals=4,start_offset=800,deal_layout='shared',weights=[.5,.5]),
        budget=Budget(max_independent_deals=4,max_games=96,max_rollouts=0,allowed_seconds=60))


class DesignLab:
    def __init__(self,store,definitions,evaluation,evolution):
        self.store,self.definitions,self.evaluation,self.evolution=store,definitions,evaluation,evolution
        self.lock=RLock();self.starts={};self.closed=False
        with closing(sqlite3.connect(store.path)) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS design_plans (id TEXT, version INTEGER, payload TEXT NOT NULL, PRIMARY KEY(id,version))')
            db.execute('CREATE TABLE IF NOT EXISTS design_events (seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT,version INTEGER,payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS design_seeds (seed INTEGER PRIMARY KEY,id TEXT,version INTEGER)')

    def event(self,identifier,version,value):
        with closing(sqlite3.connect(self.store.path)) as db,db:
            db.execute('INSERT INTO design_events(id,version,payload) VALUES (?,?,?)',(identifier,version,json.dumps({'created_at':now(),**value})))

    def raw(self,identifier,version):
        with closing(sqlite3.connect(self.store.path)) as db:
            row=db.execute('SELECT payload FROM design_plans WHERE id=? AND version=?',(identifier,version)).fetchone()
            if not row:raise KeyError(identifier)
            events=[json.loads(r[0]) for r in db.execute('SELECT payload FROM design_events WHERE id=? AND version=? ORDER BY seq',(identifier,version))]
        return json.loads(row[0]),events

    def draft(self,spec):
        if spec.parent_version is not None:self.raw(spec.plan_id,spec.parent_version)
        payload={'spec':spec.model_dump(mode='json'),'draft_hash':digest(spec.model_dump(mode='json'))}
        with closing(sqlite3.connect(self.store.path)) as db,db:
            try:db.execute('INSERT INTO design_plans VALUES (?,?,?)',(spec.plan_id,spec.version,json.dumps(payload)))
            except sqlite3.IntegrityError:raise ValueError('同じPlan ID・版は上書きできません。新しい版にしてください') from None
        self.event(spec.plan_id,spec.version,{'state':'Draft'})
        return self.get(spec.plan_id,spec.version)

    def prepare(self,spec):
        members=family(spec.evaluation,spec.between_opponents)
        if spec.evaluation.family_size is not None and spec.evaluation.family_size!=len(members):raise ValueError('登録familyと多重比較数が一致しません')
        request=EvaluationRequest.model_validate({**spec.evaluation.model_dump(mode='json'),'family_size':len(members),'timeout_seconds':min(spec.evaluation.timeout_seconds,spec.budget.allowed_seconds)})
        plans=request.plans(self.definitions);estimate=estimate_evaluation(request,self.definitions)
        estimated=spec.budget.measured_seconds_per_deal_composition*sum(request.counts) if spec.budget.measured_seconds_per_deal_composition else estimate['estimated_seconds_range'][1]
        if estimate['distinct_deals']>spec.budget.max_independent_deals or estimate['games']>spec.budget.max_games or estimate['rollout_upper_bound']>spec.budget.max_rollouts or estimated>spec.budget.allowed_seconds:raise ValueError('登録した計算予算を超えます。規模または許容予算を登録前に見直してください')
        for ref in spec.references:
            if self.store.get(ref) is None:
                try:self.evolution.raw(ref)
                except KeyError:raise ValueError('参照した実験IDがありません') from None
        manifest=[[{'reference':s.reference,'version':s.strategy_version,'parameters':s.create_strategy().parameters if hasattr(s.create_strategy(),'parameters') else {}} for s in [*p.settings,*p.opponent_entries]] for p in plans]
        return {'spec':spec.model_dump(mode='json'),'evaluation':request.model_dump(mode='json'),'plans':[p.model_dump(mode='json') for p in plans],
            'family':members,'estimate':{**estimate,'estimated_seconds':estimated},'strategy_manifest':manifest,
            'source_hashes':runtime_info()['source_sha256'],'rule_version':RULE_VERSION,'reward_version':REWARD_VERSION,'baseline_commit':BASELINE,
            'statistical_scope':'固定した候補・相手構成・配札母集団の範囲。任意の未知相手へ一般化しない。'}

    def register(self,identifier,version):
        with self.lock:
            view=self.get(identifier,version)
            if view['state']!='Draft':raise ValueError('Draftだけを登録できます')
            spec=PlanSpec.model_validate(view['spec']);registered=self.prepare(spec)
            seeds={s for p in registered['plans'] for s in p['deal_seeds']}
            with closing(sqlite3.connect(self.store.path)) as db,db:
                db.execute('BEGIN IMMEDIATE')
                for payload, in db.execute('SELECT payload FROM experiments'):
                    if seeds & set(json.loads(payload).get('config',{}).get('deal_seeds',[])):raise ValueError('計画の配札は使用済みです。パイロットと確証評価を分離し、新しいoffsetにしてください')
                try:db.executemany('INSERT INTO design_seeds VALUES (?,?,?)',[(s,identifier,version) for s in seeds])
                except sqlite3.IntegrityError:raise ValueError('配札は別Planで予約済みです') from None
                db.execute('INSERT INTO design_events(id,version,payload) VALUES (?,?,?)',(identifier,version,json.dumps({'state':'Registered','created_at':now(),'registered':registered,'plan_hash':digest(registered)})))
            return self.get(identifier,version)

    def estimate(self,spec):return self.prepare(spec)['estimate']

    def _view(self,identifier,version):
        raw,events=self.raw(identifier,version);registration=next((e for e in events if e.get('state')=='Registered'),None)
        errors=[]
        if digest(raw['spec'])!=raw['draft_hash']:errors.append('Draft内容hashが一致しません')
        if registration and (digest(registration['registered'])!=registration['plan_hash'] or registration['registered']['spec']!=raw['spec']):errors.append('登録内容hashが一致しません')
        return {'id':identifier,'version':version,**raw,'events':events,'state':'Invalidated' if errors else events[-1]['state'],
            'integrity_errors':errors,'registered':registration['registered'] if registration else None,'plan_hash':registration['plan_hash'] if registration else None}

    def _usage(self,result):
        total=0;partial=False
        for report in result['reports']:
            raw=self.evaluation.arena.get(report['arena_id'],True)
            for row in raw['results']:
                total+=sum(d['started_rollouts'] for role in row['role_records'] for d in role['decisions'])
            for position in raw.get('positions',[]):
                total+=sum(((c['decision'].get('details') or {}).get('optional_metadata') or {}).get('started_games',0) for c in position['choices'])
            partial=partial or bool(raw.get('partial_games'))
        return {'completed_games':result['completed_games'],'started_rollouts':total,'elapsed_seconds':result['elapsed_seconds'],
            'partial_role_work_unmeasured':partial,'note':'中断した未完了対局の相手役作業は下限値。時間・停止は協調方式。'}

    def _validate_result(self,registered,result):
        errors=[]
        if result['config']!=registered['evaluation'] or result['plans']!=registered['plans']:errors.append('実行設定が登録Planと一致しません')
        for report in result['reports']:
            raw=self.evaluation.arena.get(report['arena_id'],True);index=report['composition']
            if raw['config']!=registered['plans'][index] or raw['runtime']['source_sha256']!=registered['source_hashes']:errors.append('実行時の設定または実装hashが不一致です')
            if raw['rule_version']!=registered['rule_version'] or raw['reward_version']!=registered['reward_version']:errors.append('ルール・報酬の版が不一致です')
            if result['status']=='completed' and any(s['independent_deals']!=len(registered['plans'][index]['deal_seeds']) for s in report['report']['strength']):errors.append('完了データの6席順・条件が不足しています')
        if result['status']=='completed' and (len(result['reports'])!=len(registered['plans']) or result['completed_games']!=registered['estimate']['games']):errors.append('固定した対局数が完了していません')
        return errors

    def _data_hash(self,evaluation_id):
        result=self.store.get(evaluation_id)
        return digest({'evaluation':result,'arena':[self.store.get(j['arena_id']) for j in result['jobs']]}) if result else None

    def _analysis(self,registered,result):
        spec=PlanSpec.model_validate(registered['spec']);request=spec.evaluation;between=[]
        complete=result['status']=='completed';confirm=spec.interpretation=='confirmatory' and all(result['fresh_deals'])
        m=len(registered['family'])
        if spec.between_opponents:
            for a,b in combinations(result['reports'],2):
                for j,target in enumerate(request.participants[1:]):
                    values=opponent_effect_difference(a['report']['samples'][j],b['report']['samples'][j])
                    evidence=fixed_evidence(values.values(),alpha=request.alpha,comparisons=m,completed=complete,confirmatory=confirm,bound=8)
                    interval=evidence['interval'];threshold=spec.statistics.decision_threshold
                    verdict='hold'
                    if confirm and interval and (interval[0]>threshold or interval[1]<-threshold):verdict='effect_difference_detected'
                    between.append({'strategy_b':target,'first':a['name'],'second':b['name'],'direction':'second − first','evidence':evidence,
                        'verdict':verdict,'unit':'同じ独立配札の構成間効果差。構成数を標本数に足さない。'})
        per=[]
        for report in result['reports']:
            for comparison in report['report']['comparisons']:
                evidence=comparison['fixed_evidence'];interval=evidence['interval'];verdict='hold'
                cost=report['report']['strength'];parent_ms=cost[0]['decision_ms']['mean']
                child=next(s for s in cost if s['reference']==comparison['strategy_b']);child_ms=child['decision_ms']['mean']
                affordable=parent_ms is not None and child_ms is not None and child_ms<=max(.001,parent_ms)*spec.statistics.max_decision_time_ratio
                if confirm and interval and interval[0]>spec.statistics.decision_threshold and affordable:verdict='adopt_evidence'
                elif confirm and interval and interval[1]<-spec.statistics.decision_threshold:verdict='reject_evidence'
                per.append({'composition':report['name'],'strategy_b':comparison['strategy_b'],'evidence':evidence,'verdict':verdict,'time_ratio_passed':affordable})
        seconds=sum(r['elapsed_seconds'] for r in result['reports'])/sum(request.counts) if result['reports'] else None
        planning=[]
        for contrast in [*per,*between]:
            evidence=contrast['evidence']
            planning.append({'contrast':contrast.get('composition',contrast.get('first',''))+' / '+contrast['strategy_b'],
                'plan':design_sample_plan(DesignPlanningInput(observed_deals=evidence['independent_deals'],mean_difference=evidence['mean'],sd_difference=evidence['sd'],
                    minimum_effect=request.minimum_effect,alpha=request.alpha,power=request.power,comparisons=m,
                    seconds_per_deal=seconds,opponent_count=len(request.opponents),setting_count=len(request.participants),shared_deals=request.deal_layout=='shared',
                    max_deals=spec.budget.max_independent_deals,max_games=spec.budget.max_games,allowed_seconds=spec.budget.allowed_seconds,contrast_bound=8 if 'first' in contrast else 4))})
        return {'within':per,'between':between,'integrated':result['integrated'],'interpretation':spec.interpretation,'planning':planning,
            'conclusion':'探索的パイロット・少数配札では判定保留。採用証拠も自動採用ではありません。',
            'reports':result['reports'],'recommendations':result['recommendations']}

    def get(self,identifier,version):
        with self.lock:
            view=self._view(identifier,version)
            running=next((e for e in view['events'] if e.get('state')=='Running'),None)
            if view['state']=='Running' and running:
                try:
                    result=self.evaluation.get(running['evaluation_id']);errors=self._validate_result(view['registered'],result)
                    view['result']=result;view['usage']=self._usage(result)
                    if result['status']=='completed' and result['elapsed_seconds']>view['registered']['spec']['budget']['allowed_seconds']:errors.append('許容実行時間を超えました')
                    if errors:
                        self.evaluation.cancel(running['evaluation_id'])
                        self.event(identifier,version,{'state':'Invalidated','reason':' / '.join(errors),'evaluation_id':running['evaluation_id'],'usage':view['usage']})
                        return self.get(identifier,version)
                    if result['status']!='running':
                        state='Completed' if result['status']=='completed' else 'Cancelled' if result['status'] in ('cancelled','timed_out') else 'Invalidated'
                        self.event(identifier,version,{'state':state,'evaluation_id':running['evaluation_id'],'usage':view['usage'],'analysis':self._analysis(view['registered'],result),'reason':result['status'],'stop_reason':'time_budget' if result['status']=='timed_out' else next((e.get('stop_reason') for e in reversed(view['events']) if e.get('stop_reason')),None),'data_hash':self._data_hash(running['evaluation_id'])})
                        return self.get(identifier,version)
                except KeyError:
                    self.event(identifier,version,{'state':'Invalidated','reason':'参照する実験結果がありません'})
                    return self.get(identifier,version)
            if view['state'] in ('Completed','Cancelled','Invalidated'):
                final=view['events'][-1];view['analysis']=final.get('analysis');view['usage']=final.get('usage')
                if final.get('data_hash') and final['data_hash']!=self._data_hash(final['evaluation_id']):
                    view['state']='Invalidated';view['integrity_errors'].append('完了時の実験データhashが一致しません');view['analysis']=None
            view['recommendations']=self.recommendations(view)
            return view

    def recommendations(self,view):
        source=PlanSpec.model_validate(view['spec']);analysis=view.get('analysis');reasons=[]
        if view['state']=='Invalidated':reasons.append(('condition_mismatch','登録設定・hashまたは実験条件が不一致です。結果を判断に使わず、新しい版を確認してください',view['integrity_errors']))
        elif not view['registered']:reasons.append(('family_not_registered','多重比較familyはまだ事前登録されていません',{'state':view['state']}))
        if analysis:
            contrasts=[*analysis['within'],*analysis['between']]
            insufficient=[c['evidence']['independent_deals'] for c in contrasts if c['evidence']['independent_deals']<10]
            if insufficient:reasons.append(('pilot_insufficient','予備評価が不足しています。未使用の固定10配札パイロットで分散と時間を再推定してください',{'independent_deals':insufficient}))
            for p in analysis['planning']:
                if p['plan']['status']=='approximate':
                    if p['plan']['estimated_additional']>0:reasons.append(('additional_deals','最小改善幅に対する対応差の分散から追加配札が必要です',{'contrast':p['contrast'],'total':p['plan']['estimated_total']}))
                    bounded=p['plan']['bounded_cost']
                    if bounded and not all(bounded[k] is True for k in ('within_deal_budget','within_game_budget','within_time_budget')):reasons.append(('budget_shortfall','保守的判定で検出したい改善幅に対し予算が不足しています',bounded))
                    elif bounded and bounded['deals_per_composition']<=20:reasons.append(('confirmatory_ready','分散と費用の予備情報があり、確証計画を検討できる条件です。未使用検証配札で別途登録してください',bounded))
                elif p['plan']['pilot_cost'] and not all(p['plan']['pilot_cost'][k] is True for k in ('within_deal_budget','within_game_budget')):
                    reasons.append(('pilot_budget_revision','固定10配札パイロットには現在Planとは別の配札・対局予算が必要です',p['plan']['pilot_cost']))
        if len(source.evaluation.opponents)==1:reasons.append(('opponent_coverage','相手構成の検証が1種類だけです。別構成への頑健性は未確認です',{'compositions':1}))
        if view['registered']:
            definitions=[s.get('definition') for s in view['registered']['plans'][0]['settings']]
            if all(definitions):
                parent=definitions[0]
                mixed=any(sum(a!=b for a,b in zip(parent['rules'],d['rules']))>1 or sum(a!=b for a,b in zip(parent['theory_config']['theories'],d['theory_config']['theories']))>1 for d in definitions[1:])
                if mixed:reasons.append(('ablation_needed','複数の変更項目が混在しています。寄与を知りたい場合はAblationを別計画にしてください',{'participants':source.evaluation.participants}))
        references=list(dict.fromkeys([*source.references,*[e['evaluation_id'] for e in view['events'] if e.get('evaluation_id')]]))
        measured=(view.get('usage') or {}).get('elapsed_seconds',0)/sum(source.evaluation.counts) if view.get('usage') else None
        recommendations=[]
        for kind,reason,observed in reasons:
            data=source.model_dump(mode='json');data.update(created_at=now(),interpretation='exploratory',reason=reason,hypothesis='新しい配札で事前仮説を追試し、対応差の分散と計算時間を把握する。',references=references)
            request=data['evaluation'];request.update(deals=10,composition_deals=None,seed_partition='development',family_size=None)
            if 10*len(request['opponents'])*len(request['participants'])*6>360:
                request.update(participants=request['participants'][:2],opponents=request['opponents'][:2],purpose='comparison',weights=None)
            if kind=='opponent_coverage':
                current=tuple(sorted(request['opponents'][0]['strategies']))
                pair=['Random','Random'] if current!=('Random','Random') else ['Heuristic','Heuristic']
                request['opponents'].append({'name':'追加の未検証候補構成','strategies':pair});request.update(weights=None,deal_layout='shared')
            span=10 if request['deal_layout']=='shared' else 10*len(request['opponents'])
            offset=source.evaluation.start_offset+max(source.evaluation.counts)+100
            with closing(sqlite3.connect(self.store.path)) as db:used={s for s, in db.execute('SELECT seed FROM design_seeds')}
            for _,p in self.store.iter_experiments():used.update(p.get('config',{}).get('deal_seeds',[]))
            while any(s in used for s in range(offset,offset+span)) and offset<=999900:offset+=span
            if offset>999900:continue
            request['start_offset']=offset
            data['budget'].update(max_independent_deals=span,max_games=10*len(request['opponents'])*len(request['participants'])*6,measured_seconds_per_deal_composition=measured or None)
            if data['budget']['max_games']>360:continue
            recommendations.append({'kind':kind,'reason':reason,'observed':observed,'proposal':data,
                'estimated_seconds':measured*10*len(request['opponents']) if measured else None,'reference_ids':references,
                'limitation':'探索的な設計提案です。新しい版として登録・再見積もりが必要。確証準備の推薦も自動的な確証実行ではありません。'})
        return recommendations

    def start(self,identifier,version,expected_hash):
        with self.lock:
            view=self.get(identifier,version)
            if self.closed or view['state']!='Registered':raise ValueError('RegisteredのPlanだけを実行できます')
            if view['plan_hash']!=expected_hash:raise ValueError('要求したPlan Hashが一致しません')
            registered=view['registered'];spec=PlanSpec.model_validate(view['spec'])
            with closing(sqlite3.connect(self.store.path)) as db:
                owned={r[0] for r in db.execute('SELECT seed FROM design_seeds WHERE id=? AND version=?',(identifier,version))}
            if owned!={s for p in registered['plans'] for s in p['deal_seeds']}:
                self.event(identifier,version,{'state':'Invalidated','reason':'配札予約が一致しません'})
                raise ValueError('配札予約が破損しています')
            if self.prepare(spec)!=registered:
                self.event(identifier,version,{'state':'Invalidated','reason':'登録後に戦略・実装・条件が変わりました'})
                raise ValueError('登録時の設定と実装が一致しません。新しいPlanを登録してください')
            result=self.evaluation.submit(EvaluationRequest.model_validate(registered['evaluation']))
            self.event(identifier,version,{'state':'Running','evaluation_id':result['id'],'plan_hash':expected_hash})
            started=monotonic();self.starts[(identifier,version)]=started
            def monitor():
                requested=False
                while True:
                    with self.lock:
                        current=self.get(identifier,version)
                        if current['state']!='Running':break
                        if not requested and (monotonic()-started>=spec.budget.allowed_seconds or current['usage']['started_rollouts']>spec.budget.max_rollouts):
                            self.event(identifier,version,{'state':'Running','evaluation_id':result['id'],'stop_reason':'time_budget'})
                            self.evaluation.cancel(result['id']);requested=True
                    sleep(.1)
            Thread(target=monitor,daemon=True,name='design-plan').start()
            return self.get(identifier,version)

    def cancel(self,identifier,version):
        with self.lock:
            view=self.get(identifier,version)
            if view['state']=='Running':
                event=next(e for e in view['events'] if e.get('state')=='Running')
                self.evaluation.cancel(event['evaluation_id'])
            elif view['state'] in ('Draft','Registered'):self.event(identifier,version,{'state':'Cancelled','reason':'user_cancel'})
            return self.get(identifier,version)

    def invalidate(self,identifier,version,reason):
        view=self.get(identifier,version)
        if view['state']=='Running':self.cancel(identifier,version)
        self.event(identifier,version,{'state':'Invalidated','reason':reason})
        return self.get(identifier,version)

    def history(self):
        with closing(sqlite3.connect(self.store.path)) as db:keys=db.execute('SELECT id,version FROM design_plans ORDER BY rowid DESC').fetchall()
        values=[]
        for i,v in keys:
            p=self.get(i,v);spec=p['spec'];evaluation=spec['evaluation']
            values.append({'id':i,'version':v,'state':p['state'],'hypothesis':spec['hypothesis'],'interpretation':spec['interpretation'],'created_at':spec['created_at'],
                'deals':evaluation['composition_deals'] or [evaluation['deals']]*len(evaluation['opponents']),'opponents':[o['name'] for o in evaluation['opponents']],
                'estimated_seconds':p['registered']['estimate']['estimated_seconds'] if p['registered'] else None})
        return values

    def recommended_draft(self,evaluation_id,index):
        result=self.evaluation.get(evaluation_id);recommendations=result['recommendations']
        if not 0<=index<len(recommendations) or not recommendations[index].get('execution_request'):raise ValueError('この推薦にはDraft設定がありません')
        source=recommendations[index]
        spec=PlanSpec(plan_id='recommended-'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f'),created_at=datetime.now(timezone.utc),
            reason=source['reason']+' 観測値：'+json.dumps(source['observations'],ensure_ascii=False),hypothesis='新しい開発配札で対応差の分散と計算時間を把握する。',
            references=[evaluation_id],evaluation=EvaluationRequest.model_validate(source['execution_request']),between_opponents=False,
            budget=Budget(max_independent_deals=20,allowed_seconds=120))
        return self.draft(spec)

    def recommendation_from_plan(self,identifier,version,index):
        view=self.get(identifier,version)
        if not 0<=index<len(view['recommendations']):raise ValueError('推薦番号がありません')
        data=view['recommendations'][index]['proposal']
        with closing(sqlite3.connect(self.store.path)) as db:maximum=db.execute('SELECT MAX(version) FROM design_plans WHERE id=?',(identifier,)).fetchone()[0]
        data={**data,'version':maximum+1,'parent_version':version,'created_at':now()}
        return self.draft(PlanSpec.model_validate(data))

    def close(self):
        self.closed=True
        for i,v in list(self.starts):
            if self.get(i,v)['state']=='Running':self.cancel(i,v)
