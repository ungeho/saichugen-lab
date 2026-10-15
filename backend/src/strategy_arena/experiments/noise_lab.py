"""時間ノイズRと独立判断分岐Dの事前登録。旧実験の意味は変更しない。"""
from dataclasses import asdict
from typing import Literal
from math import lcm
from pydantic import Field,model_validator
from .runtime_lab import RuntimeConfig,RuntimeJobs
from .runtime_analysis import environment
from .horizon_lab import horizon_estimate
from .stopping_analysis import select_validation_positions,rule_fingerprint
from .stratification_analysis import period
from .noise_analysis import analyze_noise,analyze_divergence,study_summary
from .evolution import digest
from .lightweight_analysis import analyze_lightweight,lightweight_summary
from .multideal_analysis import analyze_multideal,multideal_summary
from .calibration_coverage import CoverageModel,inventory,fit_coverage,validate_forecast
from .budget_calibration import CalibrationModel,active_ledger,position_context,stage_span,TimedStore,breakdown,forecast,deal_progress,completion_audit,fit_calibration

def study_estimate(c):
    by={p:max((17-t for t in c.turns if ('final_round' if period(t)=='final_round_start' else period(t))==p),default=0) for p in ('early','middle','before_final_round','final_round')}
    active=[p for p in by if by[p]];ksum=sum(by[active[i%len(active)]] for i in range(c.max_positions))
    if c.revision in ('phase38','phase39','phase40'):
        models=len(c.models);path=ksum*128*models;direct=path*3
        warm=(17-min(c.turns))*16*3*models*c.warmups;extra=ksum*(c.reference_worlds+c.final_worlds)*models
        total=path+direct+warm+extra
        result={'series':'D','independent_fresh_deals':c.deals,'positions_upper':c.max_positions,
          'reconstruction_games_upper':path,'measurement_games_upper':direct,'warmup_games_upper':warm,
          'selection_games_upper':path+direct+warm,'research_overhead_games_upper':extra,'derived_games_upper':total,
          'reference_games_upper':ksum*c.reference_worlds*models,'final_games_upper':ksum*c.final_worlds*models,
          'simulated_turns_upper':total*(15-min(c.turns)),'collection_games':c.deals*len(c.collectors),
          'model_games_upper':{m:total//models for m in c.models},'estimated_seconds_range':[total*.0005,total*.003+c.deals*len(c.collectors)*.1],
          'note':'保守的上限。最大経路＋全方式直接実測＋最初の局面だけ16世界warmup＋独立参照/最終。秒は未校正で環境依存。SQLite保存・収集を含む全体250秒で技術中止。'}
        if c.revision in ('phase39','phase40'):
            result['completion_forecast']=forecast(c,result)
            result['note']='従来の未校正秒数レンジと校正後completion_forecastを区別。実行上限は設定timeout_seconds。粗粒度の処理区間を計測し、未計測は残差。'
        return result
    reconstruction=ksum*max(c.budgets)*len(c.models)*(1 if c.series=='R' else c.repeats)
    modes=len(c.measurement_modes) if c.revision=='phase37' else 2 if c.measure_stopping else 1
    warm=ksum*sum(c.budgets)*3*c.warmups*modes*len(c.models) if c.series=='R' else 0
    measured=ksum*sum(c.budgets)*3*c.measurement_repeats*modes*len(c.models) if c.series=='R' else 0
    extra=ksum*(c.reference_worlds+c.final_worlds)*len(c.models) if c.series=='D' else 0
    total=reconstruction+warm+measured+extra
    return {'series':c.series,'independent_fresh_deals':c.deals,'positions_upper':c.max_positions,'legal_count_upper':17-min(c.turns),
      'reconstruction_games_upper':reconstruction,'warmup_games_upper':warm,'measurement_games_upper':measured,
      'selection_games_upper':reconstruction+warm+measured,'research_overhead_games_upper':extra,'derived_games_upper':total,
      'simulated_turns_upper':total*(15-min(c.turns)),'collection_games':c.deals*len(c.collectors),
      'estimated_seconds_range':[total*.0005,total*(.006 if c.series=='R' and (c.measure_stopping or (c.revision=='phase37' and 'Detailed Profile' in c.measurement_modes)) else .003)+c.deals*len(c.collectors)*.1],
      'note':'Rは同一入力の反復とwarmupを実計上、計測モードの摂動は通常群と別集約。Dは最大経路を1回計算し三標本を共有。時間は未校正。'}

class StudyConfig(RuntimeConfig):
    name:str=Field(default='Series R・実行時間ノイズパイロット',min_length=1,max_length=100)
    series:Literal['R','D']='R'
    revision:Literal['phase36','phase37','phase38','phase39','phase40']='phase36'
    calibration:CoverageModel|CalibrationModel|None=None
    storage_history_rows:int|None=Field(default=None,ge=0,le=100000)
    expected_payload_bytes:int|None=Field(default=None,ge=1,le=20000000)
    measure_stages:bool=Field(default=True,strict=True)
    allow_risky_forecast:bool=Field(default=False,strict=True)
    deals:int=Field(default=1,strict=True,ge=1,le=8)
    timeout_seconds:int=Field(default=120,strict=True,ge=1,le=250)
    prior_deal_hashes:list[str]=Field(default=[],max_length=20000)
    prior_inventory_note:str=Field(default='',max_length=2000)
    measurement_modes:list[Literal['Baseline','Lightweight','Detailed Profile']]=Field(default=['Baseline','Lightweight'],min_length=2,max_length=3)
    repeats:int=Field(default=2,strict=True,ge=1,le=5)
    start_offset:int=Field(default=36000,strict=True,ge=0,le=1999900)
    max_positions:int=Field(default=1,strict=True,ge=1,le=8)
    turns:list[int]=Field(default=[13],min_length=1,max_length=8)
    measurement_repeats:int=Field(default=3,strict=True,ge=2,le=10)
    warmups:int=Field(default=1,strict=True,ge=0,le=2)
    measure_stopping:bool=Field(default=False,strict=True)
    order_seed:int=Field(default=36001,strict=True,ge=0,le=999999)
    hypothesis:str=Field(default='Rは同一入力の実時間変動を記述。Dは128世界での全事前局面の判断分岐率と独立報酬差を評価。',min_length=1,max_length=2000)

    @model_validator(mode='after')
    def adaptive_valid(self):
        if self.revision not in ('phase38','phase39','phase40') and (self.deals>4 or self.timeout_seconds>120 or self.prior_deal_hashes or self.prior_inventory_note):raise ValueError('旧版の規模・予算は維持')
        if self.revision not in ('phase39','phase40') and (self.calibration is not None or self.allow_risky_forecast):raise ValueError('校正はPhase 39のみ')
        if self.revision in ('phase39','phase40') and self.stage=='independent_validation' and self.calibration is None:raise ValueError('独立検証は校正モデルを事前固定してください')
        if self.revision in ('phase38','phase39','phase40'):
            if self.series!='D' or self.budgets!=[128] or self.repeats!=1 or self.max_positions!=self.deals:raise ValueError('Phase 38はD・128世界・1配札1局面・選択1反復を固定')
            if self.models!=['Random','Heuristic','ScoreAware'] or self.measure_stopping:raise ValueError('3モデル固定・詳細profile禁止')
            if self.measurement_modes!=['Baseline','Lightweight']:raise ValueError('直接計測はLightweight。mode設定は固定')
            if len(set(self.prior_deal_hashes))!=len(self.prior_deal_hashes) or any(len(h)!=64 or any(ch not in '0123456789abcdef' for ch in h) for h in self.prior_deal_hashes):raise ValueError('既配札Hashは重複のないSHA256')
            if self.stage=='independent_validation' and (not self.prior_deal_hashes or not self.prior_inventory_note):raise ValueError('既存配札照合の一覧と検出範囲を事前記録してください')
            if set(range(1940000,1940004))&set(range(self.start_offset,self.start_offset+self.deals)):raise ValueError('Phase 37既観測配札を再利用しません')
        if self.revision=='phase36' and self.repeats<2:raise ValueError('旧版の選択反復は2以上')
        if self.revision=='phase37':
            if len(set(self.measurement_modes))!=len(self.measurement_modes) or not {'Baseline','Lightweight'}<=set(self.measurement_modes):raise ValueError('計測modeの重複禁止、Baseline/Lightweightが必要')
            if self.measure_stopping:raise ValueError('新計測はmeasurement_modesで指定')
            if self.series=='R' and self.measurement_repeats%(3*len(self.measurement_modes)):raise ValueError('バランス順序のため測定反復は方式数×mode数の倍数')
            if self.series=='D' and self.max_positions!=self.deals:raise ValueError('Phase 37は1独立配札1局面を優先')
            if {1930000,1930001}&set(range(self.start_offset,self.start_offset+self.deals)):raise ValueError('Phase 36既観測配札を再利用しません')
        if self.evaluation_worlds!=64 or self.safety_tolerance!=0:raise ValueError('旧互換設定は固定')
        if self.max_positions<self.deals:raise ValueError('独立配札を優先し1配札1枠以上必要')
        if self.stage=='development_pilot' and (self.partition!='development' or self.start_offset+self.deals>1000000):raise ValueError('開発は開発配札だけ')
        if self.stage=='independent_validation' and (self.partition!='validation' or self.start_offset<1000000 or self.start_offset+self.deals>2000000):raise ValueError('検証は未使用検証配札だけ')
        if self.revision=='phase40':
            if self.warmups:raise ValueError('Phase40はwarmupなしで校正・検証')
            if self.calibration is not None and not isinstance(self.calibration,CoverageModel):raise ValueError('Phase40はv2校正のみ')
            if self.stage=='independent_validation' and (self.storage_history_rows is None or self.expected_payload_bytes is None):raise ValueError('保存条件を実行前に固定してください')
        elif isinstance(self.calibration,CoverageModel):raise ValueError('v2校正はPhase40のみ')
        if self.series=='R' and (self.stage!='development_pilot' or self.repeats!=2):raise ValueError('Rは開発測定系列。互換repeats=2、実反復はmeasurement_repeatsを使用')
        if self.series=='D' and self.stage=='independent_validation' and 128 not in self.budgets:raise ValueError('D検証は主要128世界を必須とします')
        if self.revision not in ('phase38','phase39','phase40') and self.series=='D' and (self.warmups!=0 or self.measure_stopping):raise ValueError('Dは時間測定をしない。warmups=0、measure_stopping=falseを指定')
        if {1900000,1900001,1910000,1910001,1920000,1920001}&set(range(self.start_offset,self.start_offset+self.deals)):raise ValueError('既観測検証配札を再利用しません')
        if study_estimate(self)['derived_games_upper']>self.max_derived_games:raise ValueError('研究派生対局の事前上限超過')
        return self

class StudyJobs(RuntimeJobs):
    kind='runtime_divergence_v1'
    config_type=StudyConfig
    estimate=staticmethod(study_estimate)

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.store=TimedStore(self.store)

    def begin_run(self,v):
        parent=super().begin_run(v)
        if v['config'].get('revision') not in ('phase39','phase40'):return parent,None
        v['stage_measurements']=[]
        return parent,active_ledger.set({'rows':v['stage_measurements'],'stack':[]}) if v['config']['measure_stages'] else None

    def finish_run(self,v,token):
        super().finish_run(v,token[0])
        if token[1] is not None:active_ledger.reset(token[1])

    def result_content(self,v):
        parent=super().result_content(v)
        return {**parent,'stage_measurements':v.get('stage_measurements',[])} if v['config'].get('revision') in ('phase39','phase40') else parent

    def collect_positions(self,c,check,progress,snapshot):
        with stage_span('collection'):return super().collect_positions(c,check,progress,snapshot)

    def calibrate(self,ids,benchmark_id=None):
        if not isinstance(ids,list) or not 1<=len(ids)<=30 or any(not isinstance(i,str) or not i.strip() for i in ids) or len(set(ids))!=len(ids):raise ValueError('校正IDは空でない文字列で重複のない1〜30件')
        model=fit_coverage([self.get(i) for i in ids],self.storage_result(benchmark_id)) if benchmark_id else fit_calibration([self.get(i) for i in ids]);return {'model':model.model_dump(mode='json'),'model_hash':digest(model.model_dump(mode='json'))}

    def calibration_inventory(self,ids):
        if not isinstance(ids,list) or not 1<=len(ids)<=30 or any(not isinstance(i,str) or not i.strip() for i in ids) or len(set(ids))!=len(ids):raise ValueError('IDは重複なし1〜30件')
        values=[]
        for i in ids:
            v=self.store.get(i)
            if v is None:raise KeyError(i)
            if not isinstance(v.get('config'),dict) or not isinstance(v.get('snapshot'),dict):raise ValueError('研究実験の形式ではありません')
            values.append({**v,'id':i})
        return inventory(values)

    def storage_benchmark(self):
        from pathlib import Path
        from .storage_benchmark import run_storage_benchmark
        e=environment(StudyConfig());e={k:e[k] for k in ('os','cpu','python')}
        v=run_storage_benchmark(Path(self.store.path).parent/'storage-benchmarks',e)
        v['id']=self.store.save(v)
        return v

    def storage_result(self,identifier):
        if not isinstance(identifier,str) or not identifier.strip():raise ValueError('保存測定IDが必要')
        v=self.store.get(identifier)
        if v is None:raise KeyError(identifier)
        if v.get('kind')!='calibration_storage_benchmark_v1':raise ValueError('保存測定ではありません')
        return {**v,'id':identifier}

    def plan_extras(self,c):
        env=environment(c);env.update(warmup=c.warmups>0,warmup_repeats=c.warmups if c.series=='R' else 0,
          measurement_repeats=c.measurement_repeats if c.series=='R' else None,
          prior_computation='Rは最大Fixed照合経路の後、設定したwarmupを実行してから測定。Dは最大経路・独立参照・最終評価だけで直接時間測定なし。',
          scope='Rの直接計時はselect呼出と任意profile設定/解除を含み、保存・収集・照合経路は除外。Dは判断分岐と独立評価のみ。',
          stop_check_scope='任意profile群だけ既存stopping関数のcall/return間を計時。profileの全イベント通知に伴う摂動を含む。通常群の判定時間はnull。')
        plan={'version':'runtime-divergence-v1','series':c.series,'stage':c.stage,'rules_version':'phase32-frozen-v1','rules_hash':rule_fingerprint(),
          'primary_comparisons':['Gap-Adaptive - Fixed','Uncertainty-Adaptive - Fixed'],'primary_budget':128 if c.series=='D' else c.budgets,
          'outcomes':['decision_divergence_rate','independent_reward_difference'] if c.series=='D' else ['runtime_distribution','instrumented_stopping_cost'],
          'sampling':'Dはselection/reference/finalの三標本。Rは同一policy seedを全測定反復で固定。',
          'unit':'Dは反復→局面→独立配札。Rは同一入力の時間分布であり測定反復は独立配札ではない。',
          'position_selection':'Phase 33の固定時点巡回、配札・得点層・収集元を均しHash順。結果を見て追加しない。',
          'denominator':'事前選択した全評価対象局面。分岐例だけを主分析しない。',
          'order':'noise-order-v1、方式×計測モードを専用seedでshuffle。warmupと測定を別に保存。','environment':env,
          'multiplicity_bound':10000,'alpha':.05,'inference':'小標本の記述。任意の統計停止なし。時間CIなし。分岐0は損失リスク0ではない。'}
        if c.revision=='phase37':
            plan.update(version='runtime-divergence-phase37-v1',revision=c.revision,measurement_modes=c.measurement_modes,positions_per_deal=1 if c.series=='D' else None,
                order='balanced-runtime-v1。方式群と群内modeを循環。測定反復数は方式数×mode数の倍数。',
                lightweight='外側wall/CPUタイマーと16世界ごとのcheckpoint計数のみ。停止関数内の細粒度タイマーなし。',
                uncertainty='配札単位の発生有無と率。分岐0の見逃し例は同じ発生確率pの独立配札という仮定例だけ。')
        if c.revision=='phase37' and c.series=='R':
            plan.update(measurement_plan_version='lightweight-comparison-v1',primary_comparisons=['Lightweight - Baseline'],
                outcomes=['paired_wall_difference','paired_relative_wall_difference','runtime_distribution'],
                secondary_comparisons=['Detailed Profile - Baseline','方式間の同一modeの時間差'])
        if c.revision in ('phase38','phase39','phase40'):
            plan.update(version='multideal-validation-phase38-v1',revision='phase38',fixed=True,
              research_questions=['128世界での対応実時間/計算量節約','独立終局報酬差','分岐率と分岐時報酬の符号'],
              primary_comparisons=['Gap-Adaptive - Fixed','Uncertainty-Adaptive - Fixed'],primary_budget=128,
              outcomes=['paired_direct_wall_difference','independent_reward_difference'],
              primary_aggregation='各配札でRandom/Heuristic/ScoreAwareを等重み、次に独立配札を等重み。モデル別・全層は副次/探索的。',
              secondary_outcomes=['derived_games_difference','simulated_turns_difference','used_worlds','early_stop_rate','decision_divergence_rate','matches_fixed','minus_self','estimated_regret','divergent_reward_signs'],
              models=c.models,collectors=c.collectors,turns=c.turns,score_classes=['strict_middle','highest','lowest','tie'],
              independent_deals=c.deals,positions_per_deal=1,selection_repeats=1,policy_worlds=128,
              reference_worlds=c.reference_worlds,final_worlds=c.final_worlds,
              order='multideal-order-v1。モデル別専用seedの初期順序を局面ordinalで循環。3配札ごとに全方式位置を訪れる。',
              warmup={'positions':1 if c.warmups else 0,'worlds':16,'repeats':c.warmups,'separate_cost':True},
              missing='未到達層を埋めない。中断/失敗/時間超過では主要集約を非表示、未完了報酬を補完しない。',
              technical_stops=['max_derived_games','timeout_seconds','implementation_error','user_cancel'],
              budget=study_estimate(c),timeout_seconds=c.timeout_seconds,seed_rule='adaptive-v1:positionHash:{policy,reference,final}。repeat:0。評価seedは選択へ渡さない。',
              inventory={'hashes':c.prior_deal_hashes,'scope':c.prior_inventory_note,'dedup':'実配札内容Hash＋同一DB予約/過去実験seed再生成。未記録資料までは保証しない。'},
              environment={**env,'scope':'Lightweight外側wall/CPU。checkpoint計数のみ。保存/収集/参照/最終は計時外。','warmup':bool(c.warmups),
                'warmup_repeats':c.warmups,'measurement_repeats':1,'prior_computation':'各局面で最大Fixed照合経路・独立参照・最終評価を先に計算。任意warmupは最初の局面のみ16世界。cold-start測定ではない。',
                'stop_check_scope':'checkpoint計数のみ。停止関数単体時間はnull、profileは使用しない。'},
              uncertainty='小標本は記述のみ。主要2比較を事前固定し層別は探索的。中間アウトカムで規模変更なし。')
        if c.revision in ('phase39','phase40'):
            plan.update(version='budget-completion-phase39-v1',revision='phase39',calibration=c.calibration.model_dump(mode='json') if c.calibration else None,
              completion_forecast=forecast(c,study_estimate(c)),measurement='粗粒度区間のwall/CPU、入れ子は排他集計、未計測は残差。ON/OFFは乱数に触れない。',
              completion_condition='全配札/局面/3モデル/全方式/参照/最終/対応計測/Plan Hash/両上限/結果保存を満たすときのみ主要確定。')
        if c.revision=='phase40':
            plan.update(version='coverage-validation-phase40-v1',revision='phase40',primary_outcomes=['forecast_error','conservative_exceedance_per_deal','plan_completion'],research_questions=['継続モデル別の単価','時点別の単価','保存負荷','未知配札の予測誤差と保守超過'],outcomes=['forecast_error','conservative_exceedance_per_deal','plan_completion'],secondary_outcomes=['decision_divergence_rate','independent_reward_difference'],calibration_scope='固定v2係数。独立検証を同版校正へ戻さない。')
        return {'study_plan':plan,'study_plan_hash':digest(plan)}

    def register(self,c):
        if c.revision in ('phase38','phase39','phase40'):
            from .evidence_lab import deal_identity
            from .rollout_quality import runtime_info
            sources=runtime_info()['source_sha256']
            if any(deal_identity(s,sources) in set(c.prior_deal_hashes) for s in range(c.start_offset,c.start_offset+c.deals)):raise ValueError('既存配札一覧との実配札Hash重複')
            if c.revision in ('phase39','phase40') and c.calibration:
                if any(deal_identity(s,sources) in set(c.calibration.source_deal_hashes) for s in range(c.start_offset,c.start_offset+c.deals)):raise ValueError('校正用配札を独立検証へ再利用しません')
                e=environment(c)
                if c.calibration.environment and any(c.calibration.environment.get(k)!=e[k] for k in ('os','cpu','python')):raise ValueError('校正環境と実行環境が異なります')
                if forecast(c,study_estimate(c))['rating']=='予算超過のおそれ' and not c.allow_risky_forecast:raise ValueError('保守予測が時間上限超過。別Planで規模を減らすかallow_risky_forecastを明示')
        if c.revision=='phase40' and c.storage_history_rows is not None:
            if c.storage_history_rows!=sum(1 for _ in self.store.iter_experiments()):raise ValueError('事前固定した履歴件数が現在のDBと異なります')
        return super().register(c)

    def start(self,identifier,expected_hash):
        v=self.get(identifier)
        if v['config'].get('revision') in ('phase38','phase39','phase40'):
            snap=v['snapshot']
            if digest(snap)!=v['condition_hash'] or digest(snap['study_plan'])!=snap['study_plan_hash'] or v['config']!=snap['config']:raise ValueError('固定PlanのHashが不一致')
        return super().start(identifier,expected_hash)

    def position_results(self,c,records,observations,check,progress):
        selected=select_validation_positions(records,c.max_positions)
        if c.revision in ('phase38','phase39','phase40') and len({r['deal_hash'] for r in selected})!=c.deals:raise ValueError('事前指定した独立配札数に到達していません。枠を補完しません')
        for ordinal,r in enumerate(selected):
            obs=observations[r['position_hash']];fn=(analyze_lightweight if c.revision=='phase37' else analyze_noise) if c.series=='R' else analyze_divergence
            context=position_context.set({'position_id':r['position_hash'],'deal_id':r['deal_id'],'deal_hash':r['deal_hash'],'period':r['period'],'turn':r['turn']})
            try:
                with stage_span('position_management'):
                    result=analyze_multideal(obs,c,r['position_hash'],ordinal,check,progress) if c.revision in ('phase38','phase39','phase40') else fn(obs,c,r['position_hash'],check,progress)
            finally:position_context.reset(context)
            if c.revision in ('phase39','phase40'):result['revision']=c.revision
            if c.revision=='phase37':result['revision']='phase37'
            yield {**r,'position_id':r['position_hash'],'observation':asdict(obs),'labels':[r['stratum']['class']],
              'search':{'reversals':[]},'validation':None,'adaptive':result}

    @staticmethod
    def summarize_positions(positions):
        with stage_span('aggregation'):
            return multideal_summary(positions) if positions and positions[0]['adaptive'].get('revision') in ('phase38','phase39','phase40') else lightweight_summary(positions) if positions and positions[0]['adaptive'].get('revision')=='phase37' else study_summary(positions)

    def get(self,identifier):
        v=super().get(identifier);v['measurement_environment']=v['snapshot'].get('study_plan',{}).get('environment')
        v['cost_summary']['scope']='研究実計算。Rは照合経路＋warmup＋測定、Dは最大経路＋参照＋最終評価。系列・計測モードを混ぜない。'
        if v['config'].get('revision')=='phase38':v['cost_summary']['scope']='Phase 38の研究実コストは最大照合経路＋全方式Lightweight直接実行＋任意warmup＋独立参照/最終。部分局面はexecution_costを参照。'
        v['series']=v['config']['series']
        v['evaluated_independent_deals']=len({p['deal_hash'] for p in v['positions']})
        v['evaluated_positions']=len(v['positions'])
        v['completion_progress']=deal_progress(v)
        if v['config'].get('revision') in ('phase39','phase40'):
            v['cost_breakdown']=breakdown(v.get('stage_measurements',[]),v['elapsed_seconds'])
            v['completion_audit']=completion_audit(v)
            if not v['completion_audit']['primary_finalized']:v['cluster_summary']=None
            prediction=v['snapshot']['study_plan']['completion_forecast'];pred=prediction.get('predicted_seconds');slow=prediction.get('conservative_seconds')
            v['forecast_validation']={'predicted_seconds':pred,'actual_seconds':v['elapsed_seconds'],'absolute_error':abs(v['elapsed_seconds']-pred) if pred is not None else None,
              'relative_error':(v['elapsed_seconds']-pred)/pred if pred else None,'conservative_exceeded':v['elapsed_seconds']>slow if slow is not None else None,
              'predicted_completion':prediction['rating'],'actual_status':v['status'],'final':v['status'] not in ('Registered','Running')}
        if v['config'].get('revision')=='phase40' and v['config'].get('calibration'):
            v['forecast_coverage_validation']=validate_forecast(v)
        return v
