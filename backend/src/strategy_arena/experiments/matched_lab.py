"""Phase44: 対応境界Dと隔離保存E。既存本番保存のトランザクションは変更しない。"""
from pathlib import Path
from typing import Literal
from pydantic import Field,model_validator
from .boundary_lab import BoundaryConfig,BoundaryJobs,boundary_estimate
from .noise_lab import StudyJobs
from .matched_analysis import matched_select,matched_report
from .storage_efficiency import StorageSpec,run_storage
from .stratification_lab import collect
from .stopping_lab import job_context
from .budget_calibration import stage_span
from .evolution import digest
from .rollout_quality import runtime_info
from .stopping_analysis import rule_fingerprint
from .design_lab import now


class MatchedConfig(BoundaryConfig):
    revision:Literal['phase44']='phase44'
    matched_series:Literal['D','E']='D'
    boundary_series:Literal['C']='C' # 三標本/既存監査を再利用。Phase43 Planとは別kind。
    matched_sources:list[Literal['Random','Heuristic','ScoreAware','Zigzag','Reverse Zigzag']]=Field(default=['Random'],min_length=1,max_length=4)
    matched_scores:list[Literal['highest','strict_middle','lowest','tie']]=Field(default=['highest','lowest'],min_length=2,max_length=2)
    small_gap_threshold:float=Field(default=.1,ge=0,le=.5,allow_inf_nan=False)
    name:str=Field(default='対応判断境界・開発確認',min_length=1,max_length=100)
    start_offset:int=Field(default=44000,strict=True,ge=0,le=1999900)
    turns:list[int]=Field(default=[10,14],min_length=1,max_length=4)
    campaign_periods:list[Literal['early','middle','before_final_round','final_round']]=Field(default=['middle','middle','final_round','final_round'],min_length=1,max_length=8)
    storage:StorageSpec=Field(default_factory=StorageSpec)

    def slots_per_period(self):return len(self.matched_sources)*len(self.matched_scores)

    @model_validator(mode='after')
    def adaptive_valid(self):
        if self.matched_series=='D':
            super().adaptive_valid()
            if len(self.matched_sources)!=self.deals or len(set(self.matched_sources))!=len(self.matched_sources):raise ValueError('各配札へ異なる収集元を事前割当')
            if len(set(self.matched_scores))!=2 or self.max_positions!=self.slots_per_period()*len(set(self.campaign_periods)) or self.positions_per_deal<len(self.matched_scores)*len(set(self.campaign_periods)):raise ValueError('全事前tupleを上限内で評価する枠が必要')
        else:
            if self.stage!='development_pilot' or self.source_ids:raise ValueError('Eは隔離測定。独立対局検証へ混ぜない')
            if self.calibration is not None:raise ValueError('EへPhase40探索予測を流用しない')
        return self


def matched_estimate(c):
    if c.matched_series=='D':return boundary_estimate(c)
    s=c.storage
    return {'derived_games_upper':0,'estimated_seconds_range':[0,c.timeout_seconds],'cases':27*(s.warmups+s.repeats),
        'fault_cases':len(s.frequencies) if s.faults else 0,'db_limit_bytes':s.db_limit_bytes,'total_limit_bytes':s.total_limit_bytes,
        'note':'隔離WAL・合成Evidence・保存のみ。本番方式/戦略性能を変更しない。時間は未校正。'}


class MatchedJobs(BoundaryJobs):
    kind='matched_boundary_storage_v1'
    config_type=MatchedConfig
    estimate=staticmethod(matched_estimate)

    def plan_extras(self,c):
        parent=super().plan_extras(c) if c.matched_series=='D' else {'study_plan':{}}
        plan={**parent['study_plan'],'version':'matched-boundary-storage-phase44-v1','series':c.matched_series,'config':c.model_dump(mode='json'),
            'rules_hash':rule_fingerprint(),'H1':'16世界Gap<=事前閾値と32〜128の保存点での先頭変更有無（主）、128時点の相違（副）。128/Finalは説明変数に使わない。',
            'selection':'seed ordinalごと収集元固定。指定時点/得点状態の席順→Hash、欠測は補完しない。',
            'matching':'同一配札・継続モデル・反復0・同世界数・合法手区分1–8/9–17。得点/時点/収集元の1因子以外を固定。未割当収集元の組は不成立。',
            'analysis':'条件別・モデルを配札内等重み、配札Bootstrap。有効配札なしは値null。H1群も配札平均。因果効果ではない。',
            'storage_scope':'Eだけ隔離新規WAL DB、合成論理集合Hash、サイズ別paddingはEnvelopeのみ。FULL同期、warmup分離、順序seed。',
            'database_layout':'結果DBの親/storage-efficiency/storage-*（tempfileで新規作成・既存DBを使わない）。絶対配置は結果へ記録。',
            'fault_scope':'Eだけ専用子プロセスが未commit中にexit17。最後のcommit検証、同キー再試行で重複排除。既存DBは対象外。'}
        return {'study_plan':plan,'study_plan_hash':digest(plan)}

    def register(self,c):
        if c.matched_series=='D':return super().register(c)
        snapshot={'config':c.model_dump(mode='json'),'sources':runtime_info()['source_sha256'],'created_at':now(),'deal_hashes':[],**self.plan_extras(c)}
        v={'experiment_kind':self.kind,'status':'Registered','config':c.model_dump(mode='json'),'snapshot':snapshot,'condition_hash':digest(snapshot),'estimate':self.estimate(c),
            'created_at':now(),'positions':[],'reproduction':None,'progress':0,'elapsed_seconds':0,'error':None}
        return self.get(self.store.save(v))

    def collect_positions(self,c,check,progress,snapshot):
        if c.matched_series=='E':return [],{}, {'independent_deals':0}
        with stage_span('collection'):
            records,observations,summary=collect(c,check,progress,span=stage_span)
            with stage_span('stratified_search'):chosen,slots,coverage=matched_select(records,c)
            summary.update(matched_slots=slots,matched_coverage=coverage,selected_hashes=[r['position_hash'] for r in chosen])
            job_context.get()['planned_positions']=chosen
        return chosen,observations,summary

    def position_results(self,c,records,observations,check,progress):
        if c.matched_series=='E':
            v=job_context.get();v['storage_result']={}
            run_storage(c.storage,Path(self.store.path).parent/'storage-efficiency',v['snapshot']['study_plan_hash'],v['storage_result'],check,progress)
        else:yield from super().position_results(c,records,observations,check,progress)

    def summarize_positions(self,positions):
        if job_context.get()['config']['matched_series']=='E':return None
        return super().summarize_positions(positions)

    def result_content(self,v):return {**super().result_content(v),**({'storage_result':v['storage_result']} if 'storage_result' in v else {})}

    def get(self,identifier):
        raw=self.store.get(identifier)
        if not raw or raw.get('experiment_kind')!=self.kind:raise KeyError(identifier)
        if raw['config']['matched_series']=='D':
            v=super().get(identifier);e=v['boundary_evidence'];v['matched_evidence']=matched_report(v,e['records'],e['complete']);e['crossed']=None
        else:
            v=StudyJobs.get(self,identifier);s=v.get('storage_result',{});spec=v['config']['storage'];complete=v['status']=='Completed' and s.get('complete',False) and len(s.get('rows',[]))==27*(spec['warmups']+spec['repeats']) and len(s.get('faults',[]))==(3 if spec['faults'] else 0)
            v['storage_evidence']={'complete':complete,'result':s,'summary':s.get('rows') if complete else None,'warning':'隔離ベンチマーク。論理内容一致でも途中永続化保証は異なる。本番性能・戦略性能へ一般化しない。'}
        return v
