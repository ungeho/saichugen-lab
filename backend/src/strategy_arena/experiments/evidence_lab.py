"""固定条件の結果を追記し、探索的な証拠蓄積を診断する。"""
from contextlib import closing
from itertools import combinations
from math import sqrt
from threading import RLock
import json
import sqlite3
import numpy as np
from pydantic import Field,model_validator
from .design_lab import StrictModel,now,PlanSpec,DesignPlanningInput,design_sample_plan
from .evolution import digest
from .evaluation_statistics import fixed_evidence
from .quality_statistics import decision_sources
from .rollout_quality import runtime_info
from ..game.cards import deal
from ..game.rewards import terminal_rewards


class SeriesSpec(StrictModel):
    series_id:str=Field(pattern=r'^[a-z][a-z0-9_-]{2,79}$')
    version:int=Field(default=1,strict=True,ge=1,le=100000)
    hypothesis:str=Field(min_length=1,max_length=3000)
    interpretation:str=Field(default='exploratory',pattern=r'^(exploratory|confirmatory)$')
    minimum_effect:float=Field(default=.5,ge=.001,le=4,allow_inf_nan=False)
    remaining_seconds:float=Field(default=120,gt=0,le=300,allow_inf_nan=False)
    other_untested_hypotheses:int=Field(default=0,strict=True,ge=0,le=1000)


class EvidenceSource(StrictModel):
    plan_id:str|None=None
    plan_version:int|None=Field(default=None,strict=True,ge=1)
    plan_hash:str|None=Field(default=None,pattern=r'^[a-f0-9]{64}$')
    evaluation_id:str|None=None
    origin:str=Field(default='new_pilot',pattern=r'^(historical_exploratory|new_pilot|confirmatory)$')

    @model_validator(mode='after')
    def valid(self):
        if bool(self.plan_id)==bool(self.evaluation_id):raise ValueError('Planまたは過去Evaluationの片方を指定してください')
        if self.plan_id and (self.plan_version is None or self.plan_hash is None):raise ValueError('Plan版とHashが必要です')
        if self.evaluation_id and self.origin!='historical_exploratory':raise ValueError('未登録の過去結果は探索的な履歴に限定します')
        return self


class Projection(StrictModel):
    additional_deals:int=Field(default=10,strict=True,ge=1,le=10000)
    allowed_seconds:float=Field(default=120,gt=0,le=100000,allow_inf_nan=False)
    seconds_per_deal:float|None=Field(default=None,gt=0,le=10000,allow_inf_nan=False)


def deal_identity(seed,source_hashes):
    """現在と同じ配札生成実装のみ再構成。手札はhash以外を保存しない。"""
    current=runtime_info()['source_sha256']
    if source_hashes.get('game/cards.py')!=current.get('game/cards.py'):raise ValueError('配札生成の実装が異なるか不明です。配札同一性を検証できません')
    hands,unused=deal(seed)
    content=[[[c.rank,c.suit] for c in h] for h in hands]+[[unused.rank,unused.suit]]
    return digest({'scheme':'actual-deal-content-v1','cards':content})


def convergence(samples,alpha,comparisons,bound=4):
    out=[]
    for n in range(1,len(samples)+1):
        values=[s['difference'] for s in samples[:n]]
        evidence=fixed_evidence(values,alpha=alpha,comparisons=comparisons,completed=True,confirmatory=False,bound=bound)
        out.append({'n':n,'deal_id':samples[n-1]['deal_id'],'mean':evidence['mean'],'sd':evidence['sd'],
            'interval':evidence['interval'],'width':evidence['interval'][1]-evidence['interval'][0] if evidence['interval'] else None,
            'elapsed_seconds':sum(s['elapsed_seconds'] for s in samples[:n]),
            'mean_change':evidence['mean']-out[-1]['mean'] if out else None})
    return out


class EvidenceLab:
    def __init__(self,store,design):
        self.store,self.design=store,design;self.lock=RLock()
        with closing(sqlite3.connect(store.path)) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS evidence_series (id TEXT,version INTEGER,payload TEXT NOT NULL,PRIMARY KEY(id,version))')
            db.execute('CREATE TABLE IF NOT EXISTS evidence_recommendations (seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT,version INTEGER,payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS evidence_entries (seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT,version INTEGER,payload TEXT NOT NULL)')

    def create(self,spec):
        payload={'spec':spec.model_dump(mode='json'),'spec_hash':digest(spec.model_dump(mode='json')),'created_at':now()}
        with closing(sqlite3.connect(self.store.path)) as db,db:
            try:db.execute('INSERT INTO evidence_series VALUES (?,?,?)',(spec.series_id,spec.version,json.dumps(payload)))
            except sqlite3.IntegrityError:raise ValueError('Series ID・版は上書きできません') from None
        return self.get(spec.series_id,spec.version)

    def raw(self,identifier,version):
        with closing(sqlite3.connect(self.store.path)) as db:
            row=db.execute('SELECT payload FROM evidence_series WHERE id=? AND version=?',(identifier,version)).fetchone()
            if not row:raise KeyError(identifier)
            entries=[json.loads(r[0]) for r in db.execute('SELECT payload FROM evidence_entries WHERE id=? AND version=? ORDER BY seq',(identifier,version))]
        return json.loads(row[0]),entries

    def extract(self,source):
        view=None
        if source.plan_id:
            view=self.design.get(source.plan_id,source.plan_version)
            if view['state']!='Completed' or view['plan_hash']!=source.plan_hash:raise ValueError('完了PlanとHashが一致しません')
            evaluation_id=next(e['evaluation_id'] for e in view['events'] if e['state']=='Running')
        else:evaluation_id=source.evaluation_id
        result=self.design.evaluation.get(evaluation_id)
        if result['status']!='completed':raise ValueError('未完了・中断結果は蓄積できません')
        config=result['config'];partition=config['seed_partition']
        if partition=='final':raise ValueError('最終評価配札は対象外です')
        if source.origin=='confirmatory' and (not view or view['spec']['interpretation']!='confirmatory'):raise ValueError('確証結果には確証Planが必要です')
        if source.origin!='confirmatory' and partition!='development':raise ValueError('探索的結果には開発用配札だけを指定してください')
        compositions=[];samples={};times={};sources=None;rules=None;rewards=None
        for report in result['reports']:
            arena=self.store.get(report['arena_id']);plan=arena['config'];hashes=decision_sources(arena)
            if not hashes or not {'game/cards.py','game/engine.py','strategies/declarative.py'}<=hashes.keys():raise ValueError('実装hash不足')
            if sources is None:sources=hashes;rules=arena['rule_version'];rewards=arena['reward_version']
            if hashes!=sources or rules!=arena['rule_version'] or rewards!=arena['reward_version']:raise ValueError('構成間の実装条件が一致しません')
            for row in arena['results']:
                if list(terminal_rewards(tuple(row['winners'])))!=row['terminal_rewards']:raise ValueError('報酬と勝者の不整合')
            if any(s['independent_deals']!=len(plan['deal_seeds']) for s in report['report']['strength']):raise ValueError('全6役割順の完了データが不足')
            compositions.append({'name':report['name'],'opponents':plan['opponent_entries']})
            for j,values in enumerate(report['report']['samples']):
                key=f"composition:{report['composition']}:target:{j}"
                rows=[]
                for seed in plan['deal_seeds']:
                    if str(seed) not in values:raise ValueError('対応配札が不足')
                    elapsed=sum(r['game_elapsed_ns'] for r in arena['results'] if r['seed']==seed)/1e9
                    rows.append({'deal_id':deal_identity(seed,hashes),'seed':seed,'difference':values[str(seed)],'elapsed_seconds':elapsed})
                if len({r['deal_id'] for r in rows})!=len(rows):raise ValueError('実験内で同じ実配札が重複しています')
                samples[key]=rows;times[key]=sum(s['elapsed_seconds'] for s in rows)
        if len(result['reports'])!=len(result['plans']):raise ValueError('相手構成が不足')
        common=result['plans'][0]
        signature={'rule_version':rules,'reward_version':rewards,'sources':sources,'strategies':common['settings'],
            'compositions':compositions,'rotations':'all-six-v1','seed_partition':partition,'metric':'terminal_reward',
            'aggregation':'mean-six-rotations-per-deal','information':'imperfect','rng_scheme':'arena-policy-v1',
            'policy_seed':common['policy_seed'],'deal_layout':config.get('deal_layout','distinct'),'weights':config.get('weights'),
            'statistics_sources':{k:v for k,v in arena['runtime']['source_sha256'].items() if k in ('experiments/evaluation_statistics.py','experiments/quality_statistics.py','experiments/evaluation_lab.py')},'alpha':config['alpha'],'family_size':len(view['registered']['family']) if view else result['reports'][0]['report']['comparison_family_size']}
        return {'source':source.model_dump(mode='json'),'evaluation_id':evaluation_id,'plan_hash':view['plan_hash'] if view else None,
            'executed_at':result.get('created_at') or (view['events'][-1]['created_at'] if view else None),
            'linked_at':now(),'signature':signature,'condition_hash':digest(signature),'samples':samples,
            'elapsed_seconds':result['elapsed_seconds'],'games':result['completed_games'],
            'data_hash':self.design._data_hash(evaluation_id),'decision_times':[r['report']['strength'] for r in result['reports']],'registered_final_analysis':view.get('analysis') if view and source.origin=='confirmatory' else None}

    def add(self,identifier,version,source):
        with self.lock:
            raw,entries=self.raw(identifier,version);spec=SeriesSpec.model_validate(raw['spec'])
            if self.get(identifier,version)['integrity_errors']:raise ValueError('既存証拠が改変されています')
            entry=self.extract(source)
            if spec.interpretation=='confirmatory' and (entries or source.origin!='confirmatory'):raise ValueError('確証Seriesは単一の確証Planだけを保持します。事後的な複数実験合算は未対応です')
            if source.origin=='confirmatory' and spec.interpretation!='confirmatory':raise ValueError('探索的Seriesに確証結果を合算しません。別Seriesに関連付けてください')
            if entries and entries[0]['condition_hash']!=entry['condition_hash']:raise ValueError('戦略・相手・ルール・seed区分・統計・実装条件が異なります')
            for old in entries:
                if old['evaluation_id']==entry['evaluation_id']:raise ValueError('同じ実験の再追加です')
                # 構成間で共有する配札は許す。実験間の配札集合の交差は全体で拒否。
                previous={s['deal_id'] for rows in old['samples'].values() for s in rows}
                incoming={s['deal_id'] for rows in entry['samples'].values() for s in rows}
                if previous&incoming:raise ValueError('重複した実配札を検出しました。独立標本として再追加できません')
            entry['entry_hash']=digest(entry)
            with closing(sqlite3.connect(self.store.path)) as db,db:
                db.execute('BEGIN IMMEDIATE')
                current=[json.loads(r[0]) for r in db.execute('SELECT payload FROM evidence_entries WHERE id=? AND version=?',(identifier,version))]
                incoming={s['deal_id'] for rows in entry['samples'].values() for s in rows}
                for old in current:
                    if old['condition_hash']!=entry['condition_hash']:raise ValueError('比較条件が異なります')
                    if incoming & {s['deal_id'] for rows in old['samples'].values() for s in rows}:raise ValueError('重複配札です')
                db.execute('INSERT INTO evidence_entries(id,version,payload) VALUES (?,?,?)',(identifier,version,json.dumps(entry)))
            view=self.get(identifier,version)
            with closing(sqlite3.connect(self.store.path)) as db,db:
                db.execute('INSERT INTO evidence_recommendations(id,version,payload) VALUES (?,?,?)',(identifier,version,json.dumps({'created_at':now(),'entry_hash':entry['entry_hash'],'recommendations':view['recommendations']})))
            return self.get(identifier,version)

    def get(self,identifier,version):
        raw,entries=self.raw(identifier,version);errors=[] if digest(raw['spec'])==raw['spec_hash'] else ['Series仕様hashが不一致'];samples={}
        for entry in entries:
            if entry['source']['plan_id']:
                try:
                    plan=self.design.get(entry['source']['plan_id'],entry['source']['plan_version'])
                    if plan['state']!='Completed' or plan['plan_hash']!=entry['plan_hash']:errors.append('参照Planの状態・Hashが不一致')
                except KeyError:errors.append('参照Planがありません')
            if digest({k:v for k,v in entry.items() if k!='entry_hash'})!=entry['entry_hash'] or self.design._data_hash(entry['evaluation_id'])!=entry['data_hash']:errors.append('参照結果または証拠hashが変わっています')
            for key,rows in entry['samples'].items():samples.setdefault(key,[]).extend(rows)
        signature=entries[0]['signature'] if entries else None
        curves={k:convergence(v,signature['alpha'],signature['family_size']) for k,v in samples.items()} if not errors else {}
        between={};integrated={}
        if signature and not errors:
            targets=len(signature['strategies'])-1;count=len(signature['compositions'])
            if signature['deal_layout']=='shared':
                for j in range(targets):
                    groups=[{r['deal_id']:r for r in samples[f'composition:{i}:target:{j}']} for i in range(count)]
                    for a,b in combinations(range(count),2):
                        rows=[{**r,'difference':groups[b][r['deal_id']]['difference']-r['difference'],'elapsed_seconds':r['elapsed_seconds']+groups[b][r['deal_id']]['elapsed_seconds']} for r in samples[f'composition:{a}:target:{j}'] if r['deal_id'] in groups[b]]
                        between[f'{b}−{a}:target:{j}']=convergence(rows,signature['alpha'],signature['family_size'],8)
                    if signature['weights'] is not None:
                        rows=[{**r,'difference':sum(w*g[r['deal_id']]['difference'] for w,g in zip(signature['weights'],groups)),'elapsed_seconds':sum(g[r['deal_id']]['elapsed_seconds'] for g in groups)} for r in samples[f'composition:0:target:{j}'] if all(r['deal_id'] in g for g in groups)]
                        integrated[str(j)]=convergence(rows,signature['alpha'],signature['family_size'])
        all_ids={s['deal_id'] for rows in samples.values() for s in rows}
        view={**raw,'entries':entries,'signature':signature,'curves':curves,'between':between,'integrated':integrated,
            'independent_deals':len(all_ids),'games':sum(e['games'] for e in entries),'elapsed_seconds':sum(e['elapsed_seconds'] for e in entries),
            'integrity_errors':errors,'state':'Invalidated' if errors else 'confirmatory_single_plan' if raw['spec']['interpretation']=='confirmatory' else 'exploratory_diagnostic',
            'time_basis':'Series elapsed_secondsは実験全体の経過秒。曲線elapsed_secondsは対象構成の完了対局の実行秒を累積し、保存・監視等の時間を含まない。','order':'実験の関連付け順→各Planの登録配札順。結果による並べ替えなし。',
            'warning':'途中区間を見て採用・棄却を判断できる保証はありません。事後的な蓄積は確証評価ではありません。'}
        with closing(sqlite3.connect(self.store.path)) as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='middle_evidence_links'").fetchone()
            view['external_references']=[{'job_id':j,'condition_hash':h,'note':n,'aggregated':False} for j,h,n in db.execute('SELECT job_id,condition_hash,note FROM middle_evidence_links WHERE series_id=? AND version=?',(identifier,version))] if exists else []
        view['recommendations']=self.recommendations(view)
        with closing(sqlite3.connect(self.store.path)) as db:
            view['recommendation_history']=[json.loads(r[0]) for r in db.execute('SELECT payload FROM evidence_recommendations WHERE id=? AND version=? ORDER BY seq',(identifier,version))]
        return view

    def history(self):
        with closing(sqlite3.connect(self.store.path)) as db:keys=db.execute('SELECT id,version FROM evidence_series ORDER BY rowid DESC').fetchall()
        return [self.get(i,v) for i,v in keys]

    def project(self,identifier,version,request):
        view=self.get(identifier,version)
        if view['integrity_errors'] or not view['signature']:raise ValueError('有効な証拠がありません')
        sig=view['signature'];count=len(sig['compositions']);settings=len(sig['strategies'])
        unit=request.seconds_per_deal or view['elapsed_seconds']/max(1,sum(len(rows) for e in view['entries'] for k,rows in e['samples'].items() if k.endswith('target:0')))
        seconds=request.additional_deals*count*unit
        projections={}
        for key,curve in view['curves'].items():
            last=curve[-1];n=last['n']+request.additional_deals
            projections[key]={'total_deals':n,'normal_approximate_full_width':3.92*last['sd']/sqrt(n) if last['n']>=10 and last['sd'] and last['sd']>0 else None}
        return {'additional_games':request.additional_deals*count*settings*6,'additional_seconds':seconds,'within_budget':seconds<=request.allowed_seconds,
            'cumulative_distinct_deals':view['independent_deals']+request.additional_deals*(1 if sig['deal_layout']=='shared' else count),
            'projections':projections,'assumption':'分散が将来も同程度という正規近似。補正前の設計診断。小標本・分散0では幅を予測せず、将来の平均や勝敗は予測しません。'}

    def recommendations(self,view):
        if view['integrity_errors'] or not view['curves']:return [{'state':'undetermined','reason':'有効な比較可能な証拠が不足しています','observed':view['integrity_errors']}]
        spec=SeriesSpec.model_validate(view['spec']);sig=view['signature'];recommendations=[]
        for key,curve in view['curves'].items():
            last=curve[-1];unit=view['elapsed_seconds']/max(1,sum(len(rows) for e in view['entries'] for k,rows in e['samples'].items() if k.endswith('target:0')))
            plan=design_sample_plan(DesignPlanningInput(observed_deals=last['n'],mean_difference=last['mean'],sd_difference=last['sd'],minimum_effect=spec.minimum_effect,
                comparisons=sig['family_size'],alpha=sig['alpha'],max_deals=10000,max_games=360,opponent_count=len(sig['compositions']),setting_count=len(sig['strategies']),
                seconds_per_deal=unit,allowed_seconds=spec.remaining_seconds,shared_deals=sig['deal_layout']=='shared'))
            state='additional_pilot' if plan['status']=='pilot_required' else 'confirmatory_plan'
            if plan['status']=='approximate' and (plan['conservative_additional']*len(sig['compositions'])*unit>spec.remaining_seconds or plan['conservative_total']*len(sig['compositions'])*len(sig['strategies'])*6>360):state='reconsider_budget'
            if state=='reconsider_budget' and spec.other_untested_hypotheses:state='prioritize_other_hypothesis'
            recommendations.append({'state':state,'reason':'配札数・対応差のばらつき・最小効果・保守的必要数と残予算からの設計推薦。弱さの証明ではありません。',
                'observed':{'contrast':key,'n':last['n'],'sd':last['sd'],'validation_replicated':False,'decision_times':[e['decision_times'] for e in view['entries']]},'planning':plan,'estimated_additional_seconds':(plan.get('conservative_additional') if plan['status']=='approximate' else plan.get('pilot_additional',10))*len(sig['compositions'])*unit})
        if len(sig['compositions'])<2:recommendations.append({'state':'add_opponents','reason':'相手構成の頑健性は未検証です','observed':{'compositions':len(sig['compositions'])}})
        return recommendations

    def draft(self,identifier,version):
        view=self.get(identifier,version)
        if view['integrity_errors'] or not view['entries']:raise ValueError('有効な参照Planがありません')
        last=next((e for e in reversed(view['entries']) if e['source']['plan_id']),None)
        if last is None:raise ValueError('Draft生成には事前登録Planへの関連付けが必要です')
        source=last['source'];plan=self.design.get(source['plan_id'],source['plan_version'])
        choices=plan['recommendations']
        if not choices:raise ValueError('利用可能なDraft提案がありません')
        return self.design.recommendation_from_plan(source['plan_id'],source['plan_version'],0)
