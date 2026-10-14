from dataclasses import asdict
from pathlib import Path
from random import Random
from threading import Lock
from uuid import uuid4
import platform
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from ..experiments.runner import derived_seed, run_experiment
from ..experiments.metrics import summarize
from ..experiments.storage import ExperimentStore
from ..game.cards import Card
from ..game.engine import Game
from ..game.rules import RULE_VERSION
from ..game.rewards import REWARD_VERSION, terminal_rewards
from ..experiments.evaluation import enrich_payload
from ..strategies.registry import create_strategy, strategy_names, configured_parameters
from ..strategies.registry import algorithm_catalog
from ..strategies.base import Decision, decide, decision_record
from ..experiments.catalog_statistics import algorithm_statistics
from ..comparison import compare_position, initial_strategy_copies, position_at
from ..branch_simulation import BranchJobs
from ..experiments.rollout_quality import StudyConfig, estimate, presets
from ..experiments.quality_jobs import QualityJobs
from ..experiments.quality_statistics import compare_saved
from ..strategies.theories import TheoryConfig, theory_catalog
from ..strategies.theory_policy import TheoryPolicy
from ..strategies.declarative import DefinitionStore,StrategyDefinition
from ..experiments.arena import ArenaPlan,ArenaRequest,arena_jobs,arena_estimate,compare_arena,KIND as ARENA_KIND
from ..experiments.evolution import Evolution, EvolutionRequest, Generation, StageRequest, Adoption, generate
from ..experiments.evaluation_lab import EvaluationJobs, EvaluationRequest, ablation_definitions, estimate_evaluation, analyze_arena
from ..experiments.evaluation_statistics import PlanningInput,plan_samples
from ..experiments.design_lab import DesignLab,PlanSpec,DesignPlanningInput,design_sample_plan,AllocationRequest,allocate,pilot_template
from ..experiments.evidence_lab import EvidenceLab,SeriesSpec,EvidenceSource,Projection
from ..experiments.zigzag_lab import zigzag_template,zigzag_result,zigzag_history
from ..experiments.middle_lab import MiddleJobs,MiddleConfig,middle_estimate
from ..experiments.stratification_lab import StratificationJobs,StratificationConfig,stratification_estimate
from ..experiments.decision_lab import DecisionJobs,DecisionConfig,decision_estimate
from ..experiments.reliability_lab import ReliabilityJobs,ReliabilityConfig
from ..rule_guide import rule_guide, judge
from contextlib import asynccontextmanager


class NewGame(BaseModel):
    seed: int = 42
    strategies: tuple[str, str, str] = ("Random", "Greedy", "Heuristic")
    information_condition: Literal["imperfect"] = "imperfect"
    capture_details: bool = True


class Action(BaseModel):
    rank: int = Field(ge=1, le=13)
    suit: int = Field(ge=0, le=3)
    turn: int = Field(ge=0, le=14)


class ExperimentConfig(NewGame):
    deals: int = Field(default=20, ge=1, le=500)
    rotate: bool = True
    capture_details: bool = False


class PositionComparison(BaseModel):
    strategies: list[str] = Field(min_length=1, max_length=32)
    seed: int = Field(default=42, strict=True, ge=-9007199254740991, le=9007199254740991)
    turn: int | None = Field(default=None, ge=0, le=14)
    player: int = Field(default=0, ge=0, le=2)
    analysis: bool = False
    information_condition: Literal["imperfect"] = "imperfect"


class BranchCard(BaseModel):
    rank: int = Field(strict=True, ge=1, le=13)
    suit: int = Field(strict=True, ge=0, le=3)


class BranchConfig(BaseModel):
    cards: list[BranchCard] = Field(min_length=1, max_length=17)
    strategies: tuple[str, str, str]
    trials: int = Field(default=100, strict=True, ge=1, le=1000)
    seed: int = Field(default=42, strict=True, ge=-9007199254740991, le=9007199254740991)
    turn: int | None = Field(default=None, ge=0, le=14)
    player: int = Field(default=0, ge=0, le=2)
    analysis: bool = False
    information_condition: Literal["imperfect"] = "imperfect"


class RuleSample(BaseModel):
    cards: list[BranchCard] = Field(min_length=3, max_length=3)


class StudyComparison(BaseModel):
    first_id: str
    second_id: str
    first_setting: str
    second_setting: str


class TheoryEvaluation(BaseModel):
    config: TheoryConfig
    seed: int = Field(default=42,strict=True,ge=0,le=9007199254740991)
    turn: int = Field(default=0,strict=True,ge=0,le=14)
    player: int = Field(default=0,strict=True,ge=0,le=2)


def create_app(database: str | Path = "experiments.sqlite3") -> FastAPI:
    jobs = BranchJobs()
    @asynccontextmanager
    async def lifespan(app):
        yield
        jobs.close()
        quality.close()
        reliability.close()
        decision.close()
        stratification.close()
        middle.close()
        design.close()
        evaluation.close()
        arena.close()
    app = FastAPI(title="Strategy Arena", lifespan=lifespan)
    sessions = {}
    lock = Lock()
    store = ExperimentStore(database)
    quality = QualityJobs(store)
    definitions=DefinitionStore(database)
    arena=arena_jobs(store)
    evolution=Evolution(store,definitions,arena)
    evaluation=EvaluationJobs(store,definitions,arena,evolution)
    design=DesignLab(store,definitions,evaluation,evolution)
    evidence=EvidenceLab(store,design)
    middle=MiddleJobs(store,design,evidence)
    stratification=StratificationJobs(store,design,evidence)
    decision=DecisionJobs(store,design,evidence)
    reliability=ReliabilityJobs(store,design,evidence)

    def evolution_call(action):
        try:return action()
        except KeyError:raise HTTPException(404,'進化実験がありません') from None
        except ValueError as error:raise HTTPException(422,str(error)) from None
        except RuntimeError as error:raise HTTPException(409,str(error)) from None

    class PlanStart(BaseModel):
        plan_hash:str=Field(pattern=r'^[a-f0-9]{64}$')
    class PlanInvalidation(BaseModel):
        reason:str=Field(min_length=1,max_length=2000)
    class RecommendedPlan(BaseModel):
        index:int=Field(default=0,strict=True,ge=0,le=100)

    @app.post('/api/design/template')
    def design_template():
        def prepare():
            for d in ablation_definitions('adaptive_ablation'):definitions.add(d)
            return pilot_template().model_dump(mode='json')
        return evolution_call(prepare)

    @app.post('/api/design/planning')
    def design_planning(request:DesignPlanningInput):return design_sample_plan(request)

    @app.post('/api/design/allocation')
    def design_allocation(request:AllocationRequest):return evolution_call(lambda:allocate(request))

    @app.post('/api/design/estimate')
    def design_estimate(request:PlanSpec):return evolution_call(lambda:design.estimate(request))

    @app.get('/api/design/plans')
    def design_history():return design.history()

    @app.post('/api/design/plans',status_code=201)
    def design_draft(request:PlanSpec):return evolution_call(lambda:design.draft(request))

    @app.get('/api/design/plans/{identifier}/{version}')
    @app.get('/api/design/plans/{identifier}/{version}/export')
    def design_read(identifier:str,version:int):return evolution_call(lambda:design.get(identifier,version))

    @app.post('/api/design/plans/{identifier}/{version}/register')
    def design_register(identifier:str,version:int):return evolution_call(lambda:design.register(identifier,version))

    @app.post('/api/design/plans/{identifier}/{version}/start',status_code=202)
    def design_start(identifier:str,version:int,request:PlanStart):return evolution_call(lambda:design.start(identifier,version,request.plan_hash))

    @app.post('/api/design/plans/{identifier}/{version}/cancel')
    def design_cancel(identifier:str,version:int):return evolution_call(lambda:design.cancel(identifier,version))

    @app.post('/api/design/plans/{identifier}/{version}/invalidate')
    def design_invalidate(identifier:str,version:int,request:PlanInvalidation):return evolution_call(lambda:design.invalidate(identifier,version,request.reason))

    @app.post('/api/design/plans/{identifier}/{version}/recommendations/draft',status_code=201)
    def design_plan_recommended(identifier:str,version:int,request:RecommendedPlan):return evolution_call(lambda:design.recommendation_from_plan(identifier,version,request.index))

    @app.post('/api/design/recommendations/{identifier}/draft',status_code=201)
    def design_recommended(identifier:str,request:RecommendedPlan):return evolution_call(lambda:design.recommended_draft(identifier,request.index))

    class MiddleStart(BaseModel):
        condition_hash:str=Field(pattern=r'^[a-f0-9]{64}$')
    class MiddleLink(BaseModel):
        series_id:str
        version:int=Field(default=1,ge=1)

    @app.post('/api/reliability/estimate')
    def reliability_preview(request:ReliabilityConfig):return evolution_call(lambda:reliability.estimate(request))
    @app.post('/api/reliability/jobs',status_code=201)
    def reliability_register(request:ReliabilityConfig):return evolution_call(lambda:reliability.register(request))
    @app.get('/api/reliability/jobs')
    def reliability_history():return reliability.history()
    @app.get('/api/reliability/jobs/{identifier}')
    @app.get('/api/reliability/jobs/{identifier}/export')
    def reliability_read(identifier:str):return evolution_call(lambda:reliability.get(identifier))
    @app.post('/api/reliability/jobs/{identifier}/start',status_code=202)
    def reliability_start(identifier:str,request:MiddleStart):return evolution_call(lambda:reliability.start(identifier,request.condition_hash))
    @app.post('/api/reliability/jobs/{identifier}/cancel')
    def reliability_cancel(identifier:str):return evolution_call(lambda:reliability.cancel(identifier))
    @app.post('/api/reliability/jobs/{identifier}/design-draft',status_code=201)
    def reliability_draft(identifier:str):return evolution_call(lambda:reliability.design_draft(identifier))
    @app.post('/api/reliability/jobs/{identifier}/evidence',status_code=201)
    def reliability_link(identifier:str,request:MiddleLink):return evolution_call(lambda:reliability.link_evidence(identifier,request.series_id,request.version))

    @app.post('/api/decision/estimate')
    def decision_preview(request:DecisionConfig):return decision_estimate(request)
    @app.post('/api/decision/jobs',status_code=201)
    def decision_register(request:DecisionConfig):return evolution_call(lambda:decision.register(request))
    @app.get('/api/decision/jobs')
    def decision_history():return decision.history()
    @app.get('/api/decision/jobs/{identifier}')
    @app.get('/api/decision/jobs/{identifier}/export')
    def decision_read(identifier:str):return evolution_call(lambda:decision.get(identifier))
    @app.post('/api/decision/jobs/{identifier}/start',status_code=202)
    def decision_start(identifier:str,request:MiddleStart):return evolution_call(lambda:decision.start(identifier,request.condition_hash))
    @app.post('/api/decision/jobs/{identifier}/cancel')
    def decision_cancel(identifier:str):return evolution_call(lambda:decision.cancel(identifier))
    @app.post('/api/decision/jobs/{identifier}/design-draft',status_code=201)
    def decision_draft(identifier:str):return evolution_call(lambda:decision.design_draft(identifier))
    @app.post('/api/decision/jobs/{identifier}/evidence',status_code=201)
    def decision_link(identifier:str,request:MiddleLink):return evolution_call(lambda:decision.link_evidence(identifier,request.series_id,request.version))

    @app.post('/api/stratification/estimate')
    def stratification_preview(request:StratificationConfig):return stratification_estimate(request)
    @app.post('/api/stratification/jobs',status_code=201)
    def stratification_register(request:StratificationConfig):return evolution_call(lambda:stratification.register(request))
    @app.get('/api/stratification/jobs')
    def stratification_history():return stratification.history()
    @app.get('/api/stratification/jobs/{identifier}')
    @app.get('/api/stratification/jobs/{identifier}/export')
    def stratification_read(identifier:str):return evolution_call(lambda:stratification.get(identifier))
    @app.post('/api/stratification/jobs/{identifier}/start',status_code=202)
    def stratification_start(identifier:str,request:MiddleStart):return evolution_call(lambda:stratification.start(identifier,request.condition_hash))
    @app.post('/api/stratification/jobs/{identifier}/cancel')
    def stratification_cancel(identifier:str):return evolution_call(lambda:stratification.cancel(identifier))
    @app.post('/api/stratification/jobs/{identifier}/design-draft',status_code=201)
    def stratification_draft(identifier:str):return evolution_call(lambda:stratification.design_draft(identifier))
    @app.post('/api/stratification/jobs/{identifier}/evidence',status_code=201)
    def stratification_link(identifier:str,request:MiddleLink):return evolution_call(lambda:stratification.link_evidence(identifier,request.series_id,request.version))

    @app.post('/api/middle/estimate')
    def middle_preview(request:MiddleConfig):return middle_estimate(request)
    @app.post('/api/middle/jobs',status_code=201)
    def middle_register(request:MiddleConfig):return evolution_call(lambda:middle.register(request))
    @app.get('/api/middle/jobs')
    def middle_history():return middle.history()
    @app.get('/api/middle/jobs/{identifier}')
    @app.get('/api/middle/jobs/{identifier}/export')
    def middle_read(identifier:str):return evolution_call(lambda:middle.get(identifier))
    @app.post('/api/middle/jobs/{identifier}/start',status_code=202)
    def middle_start(identifier:str,request:MiddleStart):return evolution_call(lambda:middle.start(identifier,request.condition_hash))
    @app.post('/api/middle/jobs/{identifier}/cancel')
    def middle_cancel(identifier:str):return evolution_call(lambda:middle.cancel(identifier))
    @app.post('/api/middle/jobs/{identifier}/design-draft',status_code=201)
    def middle_followup(identifier:str):return evolution_call(lambda:middle.design_draft(identifier))
    @app.post('/api/middle/jobs/{identifier}/evidence',status_code=201)
    def middle_evidence(identifier:str,request:MiddleLink):return evolution_call(lambda:middle.link_evidence(identifier,request.series_id,request.version))

    @app.post('/api/zigzag/template')
    def zigzag_plan_template():return zigzag_template().model_dump(mode='json')

    @app.get('/api/zigzag/plans')
    def zigzag_list():return zigzag_history(design)

    @app.get('/api/zigzag/plans/{identifier}/{version}')
    def zigzag_read(identifier:str,version:int):return evolution_call(lambda:zigzag_result(design,identifier,version))

    @app.get('/api/evidence/series')
    def evidence_history():return evidence.history()

    @app.post('/api/evidence/series',status_code=201)
    def evidence_create(request:SeriesSpec):return evolution_call(lambda:evidence.create(request))

    @app.get('/api/evidence/series/{identifier}/{version}')
    @app.get('/api/evidence/series/{identifier}/{version}/export')
    def evidence_read(identifier:str,version:int):return evolution_call(lambda:evidence.get(identifier,version))

    @app.post('/api/evidence/series/{identifier}/{version}/entries',status_code=201)
    def evidence_add(identifier:str,version:int,request:EvidenceSource):return evolution_call(lambda:evidence.add(identifier,version,request))

    @app.post('/api/evidence/series/{identifier}/{version}/projection')
    def evidence_project(identifier:str,version:int,request:Projection):return evolution_call(lambda:evidence.project(identifier,version,request))

    @app.post('/api/evidence/series/{identifier}/{version}/draft',status_code=201)
    def evidence_draft(identifier:str,version:int):return evolution_call(lambda:evidence.draft(identifier,version))

    @app.post('/api/evaluation/planning')
    def evaluation_planning(request:PlanningInput):return plan_samples(request)

    @app.post('/api/evaluation/ablation/{family}')
    def evaluation_ablation(family:Literal['reserve_ablation','adaptive_ablation']):
        def create():
            values=ablation_definitions(family)
            for d in values:definitions.add(d)
            return EvaluationRequest(name=family,participants=[d.reference for d in values],opponents=[{'name':'Random / Heuristic','strategies':['Random','Heuristic']},{'name':'Greedy / ScoreAware','strategies':['Greedy','ScoreAware']}],purpose=family).model_dump(mode='json')
        return evolution_call(create)

    @app.get('/api/evaluation/from-evolution/{identifier}')
    def evaluation_from_evolution(identifier:str):
        def create():
            value=evolution.get(identifier)
            refs=[value['parent']['id']+'@'+value['parent']['version'],*[d['id']+'@'+d['version'] for d in value['children']]]
            return EvaluationRequest(name=value['settings']['name']+' / Evaluation',participants=refs,opponents=[{'name':'Evolutionの相手','strategies':value['settings']['opponents']}],evolution_id=identifier).model_dump(mode='json')
        return evolution_call(create)

    @app.get('/api/evaluation/analyze-arena/{identifier}')
    def evaluation_analyze_arena(identifier:str):
        def analyze():
            value=arena.get(identifier,True);plan=ArenaPlan.model_validate(value['config'])
            request=EvaluationRequest(participants=[s.reference for s in plan.settings],opponents=[{'name':'保存済み相手','strategies':[o.reference for o in plan.opponent_entries]}],deals=len(plan.deal_seeds),seed_partition='development')
            return analyze_arena(value,request,fixed_complete=value['status']=='completed')
        return evolution_call(analyze)

    @app.post('/api/evaluation/estimate')
    def evaluation_estimate(request:EvaluationRequest):return evolution_call(lambda:estimate_evaluation(request,definitions))

    @app.post('/api/evaluation/studies',status_code=202)
    def evaluation_start(request:EvaluationRequest):return evolution_call(lambda:evaluation.submit(request))

    @app.get('/api/evaluation/studies')
    def evaluation_history():return evaluation.history()

    @app.get('/api/evaluation/studies/{identifier}')
    @app.get('/api/evaluation/studies/{identifier}/export')
    def evaluation_read(identifier:str):return evolution_call(lambda:evaluation.get(identifier))

    @app.post('/api/evaluation/studies/{identifier}/cancel')
    def evaluation_cancel(identifier:str):return evolution_call(lambda:evaluation.cancel(identifier))

    @app.post('/api/evolution/generate')
    def evolution_generate(request:Generation):
        return evolution_call(lambda:{'candidates':[d.model_dump(mode='json') for d in generate(definitions.get(request.parent),request)],'registered':False})

    @app.post('/api/evolution/import',status_code=201)
    def evolution_import(request:StrategyDefinition):
        return evolution_call(lambda:definitions.add(request).model_dump(mode='json'))

    @app.get('/api/evolution/experiments')
    def evolution_history():return evolution.history()

    @app.post('/api/evolution/experiments',status_code=201)
    def evolution_create(request:EvolutionRequest):return evolution_call(lambda:evolution.create(request))

    @app.get('/api/evolution/experiments/{identifier}')
    @app.get('/api/evolution/experiments/{identifier}/export')
    def evolution_read(identifier:str):return evolution_call(lambda:evolution.get(identifier))

    @app.post('/api/evolution/experiments/{identifier}/stages/{stage}',status_code=202)
    def evolution_start(identifier:str,stage:Literal['development','validation','final'],request:StageRequest):
        return evolution_call(lambda:evolution.start(identifier,stage,request))

    @app.post('/api/evolution/experiments/{identifier}/decision')
    def evolution_decide(identifier:str,request:Adoption):return evolution_call(lambda:evolution.decide(identifier,request))

    @app.get('/api/evolution/experiments/{identifier}/proposal')
    def evolution_proposal(identifier:str):return evolution_call(lambda:evolution.proposal(identifier))

    @app.get('/api/arena/strategies')
    def arena_strategies():
        declared=definitions.list()
        ids={d['id'] for d in declared}
        records=list(store.iter_experiments())
        return {'builtins':[n for n in strategy_names() if n not in ids],
                'definitions':[{**d,'reference':d['id']+'@'+d['version'],'verification':'未検証の仮説',
                    'children':[x['id']+'@'+x['version'] for x in declared if x.get('parent') and x['parent']['definition_hash']==d['definition_hash']],
                    'experiment_ids':[i for i,p in records if p.get('experiment_kind')==ARENA_KIND and any((s.get('definition') or {}).get('definition_hash')==d['definition_hash'] for s in p['config']['settings'])]} for d in declared]}

    @app.get('/api/arena/schema')
    def arena_schema():return StrategyDefinition.model_json_schema()

    @app.post('/api/arena/definitions',status_code=201)
    def arena_register(definition:StrategyDefinition):
        try:return definitions.add(definition).model_dump(mode='json')
        except ValueError as e:raise HTTPException(422,str(e)) from None

    @app.post('/api/arena/estimate')
    def arena_preview(request:ArenaRequest):
        try:return arena_estimate(request.resolve(definitions))
        except ValueError as e:raise HTTPException(422,str(e)) from None

    @app.get('/api/arena/studies')
    def arena_history():return arena.history()

    @app.post('/api/arena/studies',status_code=202)
    def arena_start(request:ArenaRequest):
        try:return arena.submit(request.resolve(definitions))
        except ValueError as e:raise HTTPException(422,str(e)) from None
        except RuntimeError as e:raise HTTPException(409,str(e)) from None

    @app.get('/api/arena/studies/{identifier}')
    def arena_read(identifier:str):
        try:return arena.get(identifier)
        except KeyError:raise HTTPException(404,'Arena実験がありません') from None

    @app.get('/api/arena/studies/{identifier}/export')
    def arena_export(identifier:str):
        try:return arena.get(identifier,full=True)
        except KeyError:raise HTTPException(404,'Arena実験がありません') from None

    @app.post('/api/arena/studies/{identifier}/cancel')
    def arena_stop(identifier:str):
        try:return arena.cancel(identifier)
        except KeyError:raise HTTPException(404,'Arena実験がありません') from None

    @app.post('/api/arena/compare')
    @app.post('/api/arena/studies/compare')
    def arena_comparison(request:StudyComparison):
        try:return compare_arena(arena.get(request.first_id,True),arena.get(request.second_id,True),request.first_setting,request.second_setting)
        except KeyError:raise HTTPException(404,'Arena実験がありません') from None
        except ValueError as e:raise HTTPException(422,str(e)) from None

    @app.get('/api/theories')
    def theories():
        return theory_catalog()

    @app.post('/api/theories/evaluate')
    def theory_evaluation(request: TheoryEvaluation):
        game=Game(request.seed)
        for _ in range(request.turn):
            game.play(tuple(game.observe(p).legal_actions[0] for p in range(3)))
        observation=game.observe(request.player)
        decision=TheoryPolicy(request.config).choose_detailed(observation,Random(0))
        return {'observation':asdict(observation),'decision':asdict(decision),
                'generation':'指定seedで先頭合法手を出して作った人工局面。実対戦の局面ではありません。'}

    @app.get("/api/quality-studies/presets")
    def quality_presets():
        return presets()

    @app.post("/api/quality-studies/estimate")
    def quality_estimate(config: StudyConfig):
        return estimate(config,[p for i,p in store.iter_experiments()])

    @app.post("/api/quality-studies/compare")
    def quality_compare(config: StudyComparison):
        try:
            first=quality.get(config.first_id,full=True)
            second=quality.get(config.second_id,full=True)
            return compare_saved(first,second,config.first_setting,config.second_setting)
        except KeyError:
            raise HTTPException(404,"保存実験が見つかりません") from None
        except ValueError as error:
            raise HTTPException(422,str(error)) from None

    @app.get("/api/quality-studies")
    def quality_history():
        return quality.history()

    @app.post("/api/quality-studies", status_code=202)
    def quality_start(config: StudyConfig):
        try:
            return quality.submit(config)
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from None

    @app.get("/api/quality-studies/{identifier}")
    def quality_get(identifier: str):
        try:
            return quality.get(identifier)
        except KeyError:
            raise HTTPException(404, "探索品質実験が見つかりません") from None

    @app.get("/api/quality-studies/{identifier}/export")
    def quality_export(identifier: str):
        try:
            return quality.get(identifier, full=True)
        except KeyError:
            raise HTTPException(404, "探索品質実験が見つかりません") from None

    @app.post("/api/quality-studies/{identifier}/cancel")
    def quality_cancel(identifier: str):
        try:
            return quality.cancel(identifier)
        except KeyError:
            raise HTTPException(404, "探索品質実験が見つかりません") from None

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/rules")
    def rules():
        return rule_guide()

    @app.post("/api/rules/judge")
    def rule_sample(config: RuleSample):
        try:
            return judge([Card(c.rank, c.suit) for c in config.cards])
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    def validate(names):
        if any(name not in strategy_names() for name in names):
            raise HTTPException(422, "未知の戦略")

    def view(session, analysis=False):
        game = session["game"]
        decisions = []
        for turn in session["decisions"]:
            visible = []
            for p, record in enumerate(turn):
                if p != 0 and not (analysis and game.finished):
                    record = {k: v for k, v in record.items() if k not in ("details", "context")}
                    record = {**record, "details_status": "hidden" if session["capture_details"] else "disabled"}
                visible.append(record)
            decisions.append(visible)
        return {"observation": asdict(game.observe(0)), "finished": game.finished,
                "terminal_rewards": terminal_rewards(game.winners) if game.finished else None,
                "reward_version": REWARD_VERSION,
                "winners": game.winners, "strategies": session["names"],
                "decisions": decisions, "rule_version": RULE_VERSION,
                "strategy_versions": session["versions"], "capture_details": session["capture_details"],
                "analysis_visible": analysis and game.finished, "information_condition": "imperfect"}

    def find(identifier):
        if identifier not in sessions:
            raise HTTPException(404, "ゲームが見つかりません")
        return sessions[identifier]

    @app.get("/api/strategies")
    def strategies():
        return strategy_names()

    @app.get("/api/algorithms")
    def algorithms():
        return algorithm_catalog()

    @app.get("/api/algorithms/{name}/statistics")
    def statistics(name: str):
        if name not in strategy_names():
            raise HTTPException(404, "戦略が見つかりません")
        return algorithm_statistics(name, store.iter_experiments())

    @app.post("/api/games")
    def new_game(config: NewGame):
        validate(config.strategies)
        identifier = str(uuid4())
        instances = [create_strategy(name) for name in config.strategies]
        session = {"game": Game(config.seed), "names": config.strategies, "decisions": [],
                   "capture_details": config.capture_details,
                   "versions": [instance.version for instance in instances],
                   "strategies": instances,
                   "rngs": [Random(derived_seed(config.seed, f"{name}:{config.strategies[:p].count(name)}"))
                            for p, name in enumerate(config.strategies)]}
        session["comparison_initial_strategies"] = initial_strategy_copies(instances)
        session["initial_rng_states"] = [rng.getstate() for rng in session["rngs"]]
        session["human_turns"] = []
        with lock:
            sessions[identifier] = session
        return {"id": identifier, **view(session)}

    @app.get("/api/games/{identifier}")
    def get_game(identifier: str, analysis: bool = False):
        with lock:
            return view(find(identifier), analysis)

    def check_comparison_player(session, player, analysis):
        if player != 0 and not (session["game"].finished and analysis):
            raise HTTPException(403, "他プレイヤーの手札を使う視点比較は、ゲーム終了後に分析表示を選んだ場合だけ利用できます。")

    @app.get("/api/games/{identifier}/comparison-position")
    def comparison_position(identifier: str, turn: int | None = Query(default=None, ge=0, le=14),
                            player: int = Query(default=0, ge=0, le=2), analysis: bool = False):
        with lock:
            session = find(identifier)
            check_comparison_player(session, player, analysis)
            try:
                _, position = position_at(session["game"], turn, player)
            except ValueError as error:
                raise HTTPException(409, str(error)) from error
            return {**position, "game_reference": {"id": identifier, "turn": position["observation"]["turn"], "player": player}}

    @app.post("/api/games/{identifier}/compare")
    def compare(identifier: str, config: PositionComparison):
        validate(config.strategies)
        if len(set(config.strategies)) != len(config.strategies):
            raise HTTPException(422, "比較する戦略は重複なしで選択してください。")
        with lock:
            session = find(identifier)
            check_comparison_player(session, config.player, config.analysis)
            try:
                result = compare_position(session, config.strategies, config.seed, config.turn, config.player)
            except ValueError as error:
                raise HTTPException(409, str(error)) from error
            result["position"]["game_reference"] = {"id": identifier, "turn": result["position"]["observation"]["turn"], "player": config.player}
            return result

    @app.post("/api/games/{identifier}/branches", status_code=202)
    def start_branches(identifier: str, config: BranchConfig):
        validate(config.strategies)
        with lock:
            session = find(identifier)
            check_comparison_player(session, config.player, config.analysis)
            try:
                observation, position = position_at(session["game"], config.turn, config.player)
            except ValueError as error:
                raise HTTPException(409, str(error)) from error
        position["game_reference"] = {"id": identifier, "turn": observation.turn, "player": observation.player}
        try:
            return jobs.submit(observation, position, [Card(c.rank, c.suit) for c in config.cards],
                               config.strategies, config.trials, config.seed)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/api/branches/{identifier}")
    def branch_status(identifier: str):
        try:
            return jobs.get(identifier)
        except KeyError as error:
            raise HTTPException(404, "分岐実験が見つかりません") from error

    @app.post("/api/branches/{identifier}/cancel")
    def cancel_branch(identifier: str):
        try:
            return jobs.cancel(identifier)
        except KeyError as error:
            raise HTTPException(404, "分岐実験が見つかりません") from error

    def step(session, action=None):
        game = session["game"]
        if game.finished:
            raise HTTPException(409, "終了済み")
        observations = [game.observe(p) for p in range(3)]
        if action is not None:
            if action.turn != observations[0].turn:
                raise HTTPException(409, "古いターンへの操作です")
            if Card(action.rank, action.suit) not in observations[0].legal_actions:
                raise HTTPException(422, "手札にないカードです")
        decisions = [Decision(Card(action.rank, action.suit), explanation="人間が選択")
                     if p == 0 and action is not None else decide(strategy, obs, rng, session["capture_details"])
                     for p, (strategy, obs, rng) in enumerate(
                         zip(session["strategies"], observations, session["rngs"]))]
        game.play(tuple(d.card for d in decisions))
        session["human_turns"].append(action is not None)
        session["decisions"].append([decision_record(d, obs, session["capture_details"])
                                     for d, obs in zip(decisions, observations)])
        return view(session)

    @app.post("/api/games/{identifier}/step")
    def auto_step(identifier: str):
        with lock:
            return step(find(identifier))

    @app.post("/api/games/{identifier}/actions")
    def human_step(identifier: str, action: Action):
        with lock:
            return step(find(identifier), action)

    @app.post("/api/experiments")
    def experiment(config: ExperimentConfig):
        validate(config.strategies)
        results = run_experiment(list(range(config.seed, config.seed + config.deals)), config.strategies, config.rotate, config.capture_details)
        payload = {"config": config.model_dump(), "rule_version": RULE_VERSION,
                   "strategy_versions": {name: create_strategy(name).version for name in config.strategies},
                   "information_condition": config.information_condition,
                   "strategy_parameters": configured_parameters(config.strategies),
                   "python": platform.python_version(), "results": results, "summary": summarize(results),
                   "reward_version": REWARD_VERSION, "result_schema_version": 2}
        payload = enrich_payload(payload)
        identifier = store.save(payload)
        return {"id": identifier, **payload}

    @app.get("/api/experiments/{identifier}")
    def get_experiment(identifier: str):
        payload = store.get(identifier)
        if payload is None:
            raise HTTPException(404, "実験が見つかりません")
        if payload.get("experiment_kind") == "rollout_quality_v1":
            return quality.get(identifier, full=True)
        return {"id": identifier, **enrich_payload(payload)}

    return app


app = create_app()
