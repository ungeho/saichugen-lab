from dataclasses import asdict
from hashlib import sha256
from itertools import permutations
from random import Random
from time import perf_counter_ns

from ..game.engine import Game
from ..strategies.registry import create_strategy


def derived_seed(seed: int, identity: str) -> int:
    return int.from_bytes(sha256(f"{seed}:{identity}".encode()).digest()[:8], "big")


def run_game(seed: int, names: tuple[str, str, str]) -> tuple[Game, list]:
    if len(names) != 3:
        raise ValueError("3戦略が必要")
    game = Game(seed)
    strategies = [create_strategy(name) for name in names]
    # 同名戦略にも独立系列を与え、座席とは別に識別する。
    identities = [f"{name}:{names[:p].count(name)}" for p, name in enumerate(names)]
    rngs = [Random(derived_seed(seed, identity)) for identity in identities]
    trace = []
    while not game.finished:
        observations = [game.observe(p) for p in range(3)]
        decisions = []
        times = []
        for strategy, observation, rng in zip(strategies, observations, rngs):
            start = perf_counter_ns()
            decisions.append(strategy.choose(observation, rng))
            times.append(perf_counter_ns() - start)
        event = game.play(tuple(d.card for d in decisions))
        trace.append({"turn": event.index, "decisions": [asdict(d) for d in decisions], "elapsed_ns": times})
    return game, trace


def run_experiment(seeds: list[int], names: tuple[str, str, str], rotate: bool = True) -> list[dict]:
    results = []
    assignments = list(dict.fromkeys(permutations(names))) if rotate else [names]
    for seed in seeds:
        for assignment in assignments:
            game, trace = run_game(seed, assignment)
            obs = game.observe(0)
            results.append({"seed": seed, "strategies": assignment,
                            "scores": obs.game_scores, "winners": game.winners,
                            "turn_wins": tuple(sum(t.winner == p for t in obs.history) for p in range(3)),
                            "elapsed_ns": tuple(sum(t["elapsed_ns"][p] for t in trace) for p in range(3))})
    return results
