"""判断境界B・交差収集C・費用計測M。既存ワーカーと三標本評価を再利用。"""
from dataclasses import asdict
from pathlib import Path
from time import perf_counter,process_time
from typing import Literal
import json
from pydantic import Field,model_validator
from .runtime_lab import RuntimeConfig
from .noise_lab import StudyJobs,study_estimate
from .adaptive_lab import AdaptiveJobs
from .campaign_analysis import CampaignCriteria,FROZEN_MODEL_HASH,campaign_forecast,campaign_summary
from .stopping_analysis import rate_interval
from .calibration_coverage import CoverageModel,normalized
from .boundary_analysis import boundary_records,boundary_summary,crossed_select,crossed_report
from .divergence_coverage import anomalies
from .stratification_lab import collect
from .stratification_analysis import period
from .budget_calibration import stage_span,active_ledger,position_context,breakdown,completion_audit
from .multideal_analysis import analyze_multideal
from .stopping_lab import job_context
from .stopping_analysis import rule_fingerprint
from .evolution import digest
from .storage import ExperimentStore
from .rollout_quality import runtime_info
from .runtime_analysis import environment
from .evidence_lab import deal_identity
from .design_lab import now


class BoundaryConfig(RuntimeConfig):
    revision:Literal['phase43']='phase43'
    series:Literal['D']='D'
    boundary_series:Literal['B','C','M']='C'
    source_ids:list[str]=Field(default=[],max_length=30)
    name:str=Field(default='判断境界・交差収集の開発確認',min_length=1,max_length=100)
    start_offset:int=Field(default=43000,strict=True,ge=0,le=1999900)
    deals:int=Field(default=1,strict=True,ge=1,le=4)
    turns:list[int]=Field(default=[14],min_length=1,max_length=4)
    max_positions:int=Field(default=4,strict=True,ge=1,le=8)
    positions_per_deal:int=Field(default=4,strict=True,ge=1,le=8)
    campaign_periods:list[Literal['early','middle','before_final_round','final_round']]=Field(default=['final_round']*4,min_length=1,max_length=8)
    models:list[Literal['Random','Heuristic','ScoreAware']]=Field(default=['Random','Heuristic','ScoreAware'],min_length=3,max_length=3)
    budgets:list[Literal[128]]=Field(default=[128],min_length=1,max_length=1)
    repeats:Literal[1]=1
    warmups:Literal[0]=0
    reference_worlds:Literal[16]=16
    final_worlds:Literal[16]=16
    calibration:CoverageModel|None=None
    campaign_criteria:CampaignCriteria=Field(default_factory=CampaignCriteria)
    storage_history_rows:int|None=Field(default=None,strict=True,ge=0,le=100000)
    expected_payload_bytes:int|None=Field(default=None,strict=True,ge=1,le=20000000)
    timeout_seconds:int=Field(default=120,strict=True,ge=1,le=250)
    prior_deal_hashes:list[str]=Field(default=[],max_length=20000)
    prior_inventory_note:str=Field(default='',max_length=2000)
    measurement_repeats:int=Field(default=3,strict=True,ge=2,le=4)
    measurement_warmups:Literal[1]=1
    measure_stages:Literal[True]=True
    order_seed:int=Field(default=43001,strict=True,ge=0,le=999999)
    hypothesis:str=Field(default='判断境界・得点と時点の交絡・収集保存費用を分けた探索的分析。因果効果や優位性の検証ではない。',min_length=1,max_length=2000)

    @model_validator(mode='after')
    def adaptive_valid(self):
        if self.models!=['Random','Heuristic','ScoreAware']:raise ValueError('3継続モデル固定')
        if self.evaluation_worlds!=64 or self.safety_tolerance!=0:raise ValueError('旧互換設定は固定')
        if len(set(self.source_ids))!=len(self.source_ids):raise ValueError('Evidence IDが重複')
        if self.boundary_series=='B':
            if not self.source_ids or self.stage!='development_pilot':raise ValueError('Bは既存Evidenceだけの探索分析')
        else:
            if self.source_ids:raise ValueError('C/Mへ過去配札を混入しません')
            if len(self.campaign_periods)!=self.max_positions or self.max_positions>self.deals*self.positions_per_deal:raise ValueError('事前時点枠・配札あたり上限と最大局面数が不一致')
            labels=[normalized(period(t)) for t in self.turns]
            if len(set(labels))!=len(labels) or any(p not in labels for p in self.campaign_periods):raise ValueError('各時点に1手番を事前指定')
            for label in set(self.campaign_periods):
                if self.campaign_periods.count(label)!=min(4,self.max_positions) and len(labels)>1:raise ValueError('複数時点では各時点4得点枠を見積もる')
            if self.boundary_series=='M' and (self.deals!=1 or self.max_positions!=1 or self.turns!=[14]):raise ValueError('Mは1配札・最終1局面の計測のみ')
            if self.stage=='development_pilot' and (self.partition!='development' or self.start_offset+self.deals>1000000):raise ValueError('開発は開発seedだけ')
            if self.stage=='independent_validation' and (self.partition!='validation' or not 1000000<=self.start_offset<self.start_offset+self.deals<=2000000 or not self.prior_deal_hashes or not self.prior_inventory_note or self.storage_history_rows is None or self.expected_payload_bytes is None):raise ValueError('未使用配札・照合範囲・保存条件を事前固定')
            if self.calibration is None or digest(self.calibration.model_dump(mode='json'))!=FROZEN_MODEL_HASH:raise ValueError('Phase40凍結モデルを変更せず指定してください')
            if len(set(self.prior_deal_hashes))!=len(self.prior_deal_hashes) or any(len(h)!=64 or any(x not in '0123456789abcdef' for x in h) for h in self.prior_deal_hashes):raise ValueError('既配札Hashが不正')
        if boundary_estimate(self)['derived_games_upper']>self.max_derived_games:raise ValueError('事前派生対局上限超過')
        return self


def boundary_estimate(c):
    if c.boundary_series=='B':return {'derived_games_upper':0,'estimated_seconds_range':[0, min(30,c.timeout_seconds)],'note':'既存Evidenceの読込・分析のみ。独立配札を追加しない。'}
    proxy=c.model_copy(update={'revision':'phase41'})
    result=study_estimate(proxy);result['completion_forecast']=campaign_forecast(proxy,result)
    f=result['completion_forecast'];f['warnings']=sorted(set(f['warnings']+['交差収集/反復保存測定の追加費用は未校正。係数を更新しない。']))
    result['estimated_seconds_range']=[f['predicted_seconds'],f['conservative_seconds']]
    result.update(collection_games=c.deals*len(c.collectors)*(c.measurement_repeats+1 if c.boundary_series=='M' else 1),
        scanned_positions_upper=c.deals*len(c.collectors)*len(c.turns)*3,independent_fresh_deals=c.deals,
        measurement_note='Mは同じ配札でwarmup1+measured反復。ON/OFFは固定探索結果の保存段階だけを対応比較。探索反復ではない。')
    return result


class BoundaryJobs(StudyJobs):
    kind='decision_boundary_v1'
    config_type=BoundaryConfig
    estimate=staticmethod(boundary_estimate)

    def plan_extras(self,c):
        plan={'version':'decision-boundary-phase43-v1','series':c.boundary_series,'config':c.model_dump(mode='json'),
            'rules_hash':rule_fingerprint(),'role':'historical_exploratory' if c.boundary_series=='B' else 'crossed_exploratory' if c.boundary_series=='C' else 'measurement_only',
            'selection':'4時点×4得点状態の有限収集。campaign_periodsで評価対象を別指定。得点層→配札使用数→収集元→seed→席→Hash。結果/Gap/分岐で選ばない。各評価セル1枠。',
            'missing':'取得なし・配札/総枠上限・対象外を区別。別配札で補完しない。',
            'unit':'配札。複数視点・時点・モデル・測定反復は独立配札ではない。',
            'seed_rule':'既存adaptive-v1:positionHash:{policy,reference,final},repeat:0。64bit十進文字列。',
            'measurement':'Lightweight排他的wall/CPU。Mはwarmupとmeasuredを分離、保存ON/OFF順を反復ごと交互化。',
            'completion':'全配札収集・全選択局面/モデル/独立評価・Plan/予算/保存一致。欠測セルは評価完了に数えない。',
            'source_evidence':[{ 'id':i,'payload_hash':digest(self.store.get(i))} for i in c.source_ids],
            'environment':environment(c),'completion_forecast':self.estimate(c).get('completion_forecast')}
        return {'study_plan':plan,'study_plan_hash':digest(plan)}

    def register(self,c):
        if c.boundary_series=='B':
            for i in c.source_ids:
                v=self.store.get(i)
                if not v or v.get('config',{}).get('revision') not in ('phase36','phase37','phase38','phase39','phase40','phase41','phase42') and v.get('experiment_kind')!='stopping_runtime_v1':raise ValueError('BはPhase35〜42の保存Evidenceを指定')
            snapshot={'config':c.model_dump(mode='json'),'sources':runtime_info()['source_sha256'],'created_at':now(),'deal_hashes':[],**self.plan_extras(c)}
            value={'experiment_kind':self.kind,'status':'Registered','config':c.model_dump(mode='json'),'snapshot':snapshot,'condition_hash':digest(snapshot),
                'estimate':self.estimate(c),'created_at':now(),'positions':[],'reproduction':None,'progress':0,'elapsed_seconds':0,'error':None}
            return self.get(self.store.save(value))
        e=environment(c)
        if any(e[k]!=c.calibration.environment[k] for k in ('os','cpu','python')):raise ValueError('校正環境と異なります')
        if self.estimate(c)['completion_forecast']['conservative_seconds']>c.timeout_seconds:raise ValueError('保守予測が時間上限を超えます。新規Planを縮小してください')
        if c.storage_history_rows is not None and c.storage_history_rows!=sum(1 for _ in self.store.iter_experiments()):raise ValueError('履歴件数が事前条件と不一致')
        hashes={deal_identity(s,runtime_info()['source_sha256']) for s in range(c.start_offset,c.start_offset+c.deals)}
        if hashes & (set(c.prior_deal_hashes)|set(c.calibration.source_deal_hashes)):raise ValueError('既使用配札を再利用しません')
        return AdaptiveJobs.register(self,c)

    def begin_run(self,v):
        parent=super().begin_run(v);v['stage_measurements']=[];v['measurement_trials']=[]
        return parent,active_ledger.set({'rows':v['stage_measurements'],'stack':[]})

    def start(self,identifier,expected_hash):
        v=self.get(identifier)
        if digest(v['snapshot']['study_plan'])!=v['snapshot']['study_plan_hash']:raise ValueError('Plan Hashが不一致')
        return super().start(identifier,expected_hash)

    def finish_run(self,v,token):
        super().finish_run(v,token[0]);active_ledger.reset(token[1])

    def result_content(self,v):return {**super().result_content(v),'stage_measurements':v.get('stage_measurements',[]),'measurement_trials':v.get('measurement_trials',[]),**({'boundary_analysis':v['boundary_analysis']} if 'boundary_analysis' in v else {})}

    def collect_positions(self,c,check,progress,snapshot):
        if c.boundary_series=='B':
            values=[]
            for source in snapshot['study_plan']['source_evidence']:
                check();raw=self.store.get(source['id'])
                if digest(raw)!=source['payload_hash']:raise ValueError('登録後に元Evidenceが変わりました')
                values.append({**raw,'id':source['id']});progress()
            with stage_span('aggregation'):rows,inventory=boundary_records(values)
            return [],{}, {'boundary_records':rows,'evidence_inventory':inventory,'independent_deals':0}
        with stage_span('collection'):
            if c.boundary_series=='M':
                reference=None
                for repeat in range(c.measurement_repeats+1):
                    check();phase='warmup' if repeat==0 else 'measured';start=len(job_context.get()['stage_measurements']);wall=perf_counter();cpu=process_time()
                    records,observations,summary=collect(c,check,lambda:None,span=stage_span)
                    key=digest(records)
                    if reference is not None and key!=reference:raise ValueError('収集反復の意味論不一致')
                    reference=key
                    job_context.get()['measurement_trials'].append({'kind':'collection','phase':phase,'repeat':repeat,'content_hash':key,
                        'wall_seconds':perf_counter()-wall,'cpu_seconds':process_time()-cpu,
                        'interval_ids':[r['id'] for r in job_context.get()['stage_measurements'][start:]]})
                    progress()
            else:records,observations,summary=collect(c,check,progress,span=stage_span)
            with stage_span('stratified_search'):chosen,cells=crossed_select(records,c)
            for r in records:r.update(population='fresh',seed_partition=c.partition)
            for r in chosen:r.update(population='fresh',seed_partition=c.partition)
            summary.update(crossed_cells=cells,selected_hashes=[r['position_hash'] for r in chosen])
            job_context.get()['planned_positions']=chosen
        return chosen,observations,summary

    def position_results(self,c,records,observations,check,progress):
        for ordinal,r in enumerate(records):
            check();token=position_context.set({'position_id':r['position_hash'],'deal_id':r['deal_id'],'deal_hash':r['deal_hash'],'period':r['period'],'turn':r['turn']})
            try:
                with stage_span('position_management'):a=analyze_multideal(observations[r['position_hash']],c,r['position_hash'],ordinal,check,progress)
            finally:position_context.reset(token)
            if anomalies([{'position_hash':r['position_hash'],'adaptive':a}]):raise ValueError('早期停止なしの判断分岐')
            item={**r,'position_id':r['position_hash'],'observation':asdict(observations[r['position_hash']]),'labels':[], 'search':{'reversals':[]},'validation':None,'adaptive':a}
            if c.boundary_series=='M':self.measure_storage(item,c,check,progress)
            yield item

    def measure_storage(self,item,c,check,progress):
        root=Path(self.store.path).parent/'boundary-measurements';root.mkdir(exist_ok=True)
        # 専用新規DB。既存実験DBを再利用/削除しない。
        path=root/(self.active+'.sqlite');store=ExperimentStore(path);identifier=store.save({'warmup_placeholder':True})
        payload={'evidence':item};expected=digest(payload)
        for repeat in range(c.measurement_repeats+1):
            phase='warmup' if repeat==0 else 'measured'
            for save in ([True,False] if repeat%2==0 else [False,True]):
                check();start=len(job_context.get()['stage_measurements']);wall=perf_counter();cpu=process_time()
                if save:
                    with stage_span('measurement_write'):store.update(identifier,payload)
                    with stage_span('measurement_read'):value=store.get(identifier)
                else:
                    with stage_span('memory_serialize'):value=json.loads(json.dumps(payload))
                with stage_span('measurement_aggregation'):actual=digest(value)
                if actual!=expected:raise ValueError('保存ON/OFFの意味論不一致')
                job_context.get()['measurement_trials'].append({'kind':'storage','phase':phase,'repeat':repeat,'save':save,'content_hash':actual,
                    'wall_seconds':perf_counter()-wall,'cpu_seconds':process_time()-cpu,'database_bytes':path.stat().st_size,'history_rows':1,
                    'interval_ids':[r['id'] for r in job_context.get()['stage_measurements'][start:]],'scope':'固定探索結果の保存・読込のみ。探索ON/OFFの比較ではない。'})
                progress()

    def summarize_positions(self,positions):
        v=job_context.get()
        with stage_span('aggregation'):
            if v['config']['boundary_series']=='B':
                s=v.get('collection_summary') or {};rs=s.get('boundary_records',[]);inventory=s.get('evidence_inventory',[])
            else:rs,inventory=boundary_records([{**v,'id':self.active}])
            # 状態遷移前なので品質はGET時の最終状態でも再確認する。
            v['boundary_analysis']={'summary':boundary_summary(rs),'inventory':inventory}
        return None

    def get(self,identifier):
        v=super().get(identifier);series=v['config']['boundary_series'];c=v['config']
        v['cost_summary']['scope']='Bは保存Evidenceの分析のみ。Cは新規交差局面、Mは収集反復と固定結果の保存計測。系列の費用/標本を混合しない。'
        if series=='B':
            summary=v.get('collection_summary') or {};rs=summary.get('boundary_records',[])
            complete=v['status']=='Completed';report=boundary_summary(rs) if complete else None
            v['boundary_evidence']={'series':'B','complete':complete,'records':rs,'inventory':summary.get('evidence_inventory',[]),'summary':report}
        else:
            rs,inventory=boundary_records([v]);summary=v.get('collection_summary') or {};n=len(summary.get('selected_hashes',[]))
            proxy={**v,'config':{**c,'deals':len({p['deal_hash'] for p in v['positions']}),'max_positions':n}}
            checks=completion_audit(proxy)['checks'];checks.update(all_collected=summary.get('independent_deals')==c['deals'],all_selected=n==len(v['positions']),no_anomalies=not any(r['anomaly'] for r in rs))
            if series=='M':
                trials=v.get('measurement_trials',[])
                checks['all_measurement_trials']=len(trials)==(c['measurement_repeats']+1)*3 and len({t['content_hash'] for t in trials if t['kind']=='storage'})==1
            complete=all(checks.values());v['boundary_evidence']={'series':series,'complete':complete,'records':rs,'inventory':inventory,'checks':checks,
                'crossed':crossed_report(v,rs,complete) if series=='C' else None,'summary':boundary_summary(rs) if complete else None}
            if series=='C':
                paired=campaign_summary(v['positions'],CampaignCriteria(**c['campaign_criteria']),complete=complete)['primary']
                if paired:
                    for row in paired:
                        row['role']='exploratory_crossed';row['divergence_interval']=rate_interval([d['diverged'] for d in row['paired_deals']],2) if row['method']!='Fixed' else [0.,0.]
                v['boundary_evidence']['paired_outcomes']=paired
        v['boundary_evidence'].update(measurement_breakdown=breakdown(v.get('stage_measurements',[]),v['elapsed_seconds']),measurement_trials=v.get('measurement_trials',[]),
            warning='B/C/Mを混合集計しない。全結果は探索的。配札内の相関と収集元による交絡が残る。未完了時は部分Evidenceのみ。')
        v['boundary_evidence']['measurement_breakdown']['unmeasured_components']=['世界生成/継続判断/報酬の探索内内訳','SQLite書込内のJSON直列化とI/Oの内訳','最終保存・API応答等']
        for row in v['boundary_evidence']['measurement_breakdown']['stages'].values():row['share_of_total']=row['wall_seconds']/v['elapsed_seconds'] if v['elapsed_seconds'] else None
        v['boundary_evidence']['measurement_phases']={}
        for phase in ('warmup','measured'):
            trials=[t for t in v.get('measurement_trials',[]) if t['phase']==phase];ids={i for t in trials for i in t['interval_ids']}
            rows=[r for r in v.get('stage_measurements',[]) if r['id'] in ids]
            v['boundary_evidence']['measurement_phases'][phase]=breakdown(rows,sum(t['wall_seconds'] for t in trials))
        v['boundary_evidence']['forecast']=v['snapshot']['study_plan']['completion_forecast']
        return v
