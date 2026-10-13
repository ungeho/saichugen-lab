from hashlib import sha256
from itertools import permutations
from random import Random
from time import perf_counter_ns

from ..game.engine import Game
from ..strategies.registry import create_strategy
from ..strategies.base import decide, decision_record


def derived_seed(seed: int, identity: str) -> int:
    return int.from_bytes(sha256(f"{seed}:{identity}".encode()).digest()[:8], "big")


def _play_game(seed: int, names: tuple[str, str, str], capture_details: bool, capture_trace: bool):
    if len(names) != 3:
        raise ValueError("3戦略が必要")
    game = Game(seed)
    strategies = [create_strategy(name) for name in names]
    # 同名戦略にも独立系列を与え、座席とは別に識別する。
    identities = [f"{name}:{names[:p].count(name)}" for p, name in enumerate(names)]
    rngs = [Random(derived_seed(seed, identity)) for identity in identities]
    trace = []
    total_times = [0, 0, 0]
    while not game.finished:
        observations = [game.observe(p) for p in range(3)]
        decisions = []
        times = []
        for p, (strategy, observation, rng) in enumerate(zip(strategies, observations, rngs)):
            start = perf_counter_ns()
            decisions.append(decide(strategy, observation, rng, capture_details))
            times.append(perf_counter_ns() - start)
            total_times[p] += times[-1]
        event = game.play(tuple(d.card for d in decisions))
        if capture_trace:
            trace.append({"turn": event.index, "decisions": [decision_record(d, obs, capture_details)
                          for d, obs in zip(decisions, observations)], "elapsed_ns": times})
    return game, trace, tuple(total_times)


def run_game(seed: int, names: tuple[str, str, str], capture_details: bool = False) -> tuple[Game, list]:
    game, trace, _ = _play_game(seed, names, capture_details, True)
    return game, trace


def run_experiment(seeds: list[int], names: tuple[str, str, str], rotate: bool = True, capture_details: bool = False) -> list[dict]:
    results = []
    assignments = list(dict.fromkeys(permutations(names))) if rotate else [names]
    for seed in seeds:
        for assignment in assignments:
            game, trace, times = _play_game(seed, assignment, capture_details, capture_details)
            obs = game.observe(0)
            results.append({"seed": seed, "strategies": assignment,
                            "scores": obs.game_scores, "winners": game.winners,
                            "turn_wins": tuple(sum(t.winner == p for t in obs.history) for p in range(3)),
                            "elapsed_ns": times})
            if capture_details:
                results[-1]["decision_trace"] = trace
    return results
