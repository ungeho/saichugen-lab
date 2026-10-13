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


def create_app(database: str | Path = "experiments.sqlite3") -> FastAPI:
    jobs = BranchJobs()
    @asynccontextmanager
    async def lifespan(app):
        yield
        jobs.close()
        quality.close()
    app = FastAPI(title="Strategy Arena", lifespan=lifespan)
    sessions = {}
    lock = Lock()
    store = ExperimentStore(database)
    quality = QualityJobs(store)

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
