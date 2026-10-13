from dataclasses import asdict
from pathlib import Path
from random import Random
from threading import Lock
from uuid import uuid4
import platform
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ..experiments.runner import derived_seed, run_experiment
from ..experiments.metrics import summarize
from ..experiments.storage import ExperimentStore
from ..game.cards import Card
from ..game.engine import Game
from ..game.rules import RULE_VERSION
from ..strategies.registry import create_strategy, strategy_names


class NewGame(BaseModel):
    seed: int = 42
    strategies: tuple[str, str, str] = ("Random", "Greedy", "Heuristic")
    information_condition: Literal["imperfect"] = "imperfect"


class Action(BaseModel):
    rank: int = Field(ge=1, le=13)
    suit: int = Field(ge=0, le=3)
    turn: int = Field(ge=0, le=14)


class ExperimentConfig(NewGame):
    deals: int = Field(default=20, ge=1, le=500)
    rotate: bool = True


def create_app(database: str | Path = "experiments.sqlite3") -> FastAPI:
    app = FastAPI(title="Strategy Arena")
    sessions = {}
    lock = Lock()
    store = ExperimentStore(database)

    def validate(names):
        if any(name not in strategy_names() for name in names):
            raise HTTPException(422, "未知の戦略")

    def view(session):
        game = session["game"]
        return {"observation": asdict(game.observe(0)), "finished": game.finished,
                "winners": game.winners, "strategies": session["names"],
                "decisions": session["decisions"], "rule_version": RULE_VERSION,
                "information_condition": "imperfect"}

    def find(identifier):
        if identifier not in sessions:
            raise HTTPException(404, "ゲームが見つかりません")
        return sessions[identifier]

    @app.get("/api/strategies")
    def strategies():
        return strategy_names()

    @app.post("/api/games")
    def new_game(config: NewGame):
        validate(config.strategies)
        identifier = str(uuid4())
        session = {"game": Game(config.seed), "names": config.strategies, "decisions": [],
                   "strategies": [create_strategy(name) for name in config.strategies],
                   "rngs": [Random(derived_seed(config.seed, f"{name}:{config.strategies[:p].count(name)}"))
                            for p, name in enumerate(config.strategies)]}
        with lock:
            sessions[identifier] = session
        return {"id": identifier, **view(session)}

    @app.get("/api/games/{identifier}")
    def get_game(identifier: str):
        with lock:
            return view(find(identifier))

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
        from ..strategies.base import Decision
        decisions = [Decision(Card(action.rank, action.suit), explanation="人間が選択")
                     if p == 0 and action is not None else strategy.choose(obs, rng)
                     for p, (strategy, obs, rng) in enumerate(
                         zip(session["strategies"], observations, session["rngs"]))]
        game.play(tuple(d.card for d in decisions))
        session["decisions"].append([asdict(d) for d in decisions])
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
        results = run_experiment(list(range(config.seed, config.seed + config.deals)), config.strategies, config.rotate)
        payload = {"config": config.model_dump(), "rule_version": RULE_VERSION,
                   "strategy_versions": {name: create_strategy(name).version for name in config.strategies},
                   "information_condition": config.information_condition,
                   "python": platform.python_version(), "results": results, "summary": summarize(results)}
        identifier = store.save(payload)
        return {"id": identifier, **payload}

    @app.get("/api/experiments/{identifier}")
    def get_experiment(identifier: str):
        payload = store.get(identifier)
        if payload is None:
            raise HTTPException(404, "実験が見つかりません")
        return {"id": identifier, **payload}

    return app


app = create_app()
