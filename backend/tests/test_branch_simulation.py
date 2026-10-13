from dataclasses import fields
from random import Random
from time import sleep, monotonic
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from strategy_arena.api.app import create_app
from strategy_arena.branch_simulation import sampled_game, simulate, aggregate, BranchJobs
from strategy_arena.game.engine import Game
from strategy_arena.game.observation import Observation
from strategy_arena.strategies.base import Decision
from strategy_arena.strategies.registry import register

def position(turn=7):
    game = Game(42)
    for _ in range(turn):
        game.play(tuple(game.observe(p).hand[0] for p in range(3)))
    return game

def wait(manager, identifier):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        job = manager.get(identifier)
        if job["status"] not in ("running", "cancelling"):
            return job
        sleep(.01)
    raise AssertionError("job did not finish")

def test_sampled_world_valid_and_target_observation_preserved():
    obs = position().observe(0)
    worlds = [sampled_game(obs, Random(s)) for s in range(5)]
    assert all(w.observe(0) == obs for w in worlds)
    assert len({w.observe(1).hand for w in worlds}) > 1
    for w in worlds:
        remaining = [c for p in range(3) for c in w.observe(p).hand]
        assert len(set(remaining)) == len(remaining)
        assert not set(remaining).intersection(c for t in obs.history for c in t.cards)

def test_reproducible_order_independent_and_original_unchanged():
    game = position()
    before = deepcopy(game.__dict__)
    obs = game.observe(0)
    cards = obs.hand[:2]
    result = simulate(obs, {"snapshot_id": "test"}, cards, ("Random", "Greedy", "Conservative"), 8, 123)
    assert result == simulate(obs, {"snapshot_id": "test"}, cards, ("Random", "Greedy", "Conservative"), 8, 123)
    reverse = simulate(obs, {"snapshot_id": "test"}, cards[::-1], ("Random", "Greedy", "Conservative"), 8, 123)
    assert result["candidates"] == reverse["candidates"][::-1]
    assert game.__dict__ == before
    for row in result["candidates"]:
        assert sum(row["rank_distribution"].values()) == 8
        assert row["win_rate"] == row["wins"] / 8

class Recorder:
    name = "BranchRecorder"
    version = "1"
    calls = []
    def choose(self, obs, rng):
        self.calls.append((obs, rng.getstate()))
        assert set(f.name for f in fields(obs)) == set(f.name for f in fields(Observation))
        return Decision(obs.hand[0])

register(Recorder.name, Recorder)

def test_shared_world_rng_private_observations_and_continuation():
    obs = position(14).observe(0)
    Recorder.calls.clear()
    simulate(obs, {}, obs.hand[:2], (Recorder.name,) * 3, 1, 1)
    # Target first action is forced: only the two opponents are called in each branch.
    assert len(Recorder.calls) == 4
    assert Recorder.calls[:2] == Recorder.calls[2:]
    assert [o.player for o, _ in Recorder.calls] == [1, 2, 1, 2]
    assert all(o.hand != obs.hand for o, _ in Recorder.calls)

def test_aggregate_ties_and_statistics():
    card = position().observe(0).hand[0]
    rows = [{"score": 2, "win": 1, "rank": "1–3"}, {"score": 4, "win": 0, "rank": "1"}]
    result = aggregate(card, rows)
    assert result["win_rate"] == .5
    assert result["average_score"] == 3
    assert result["score_std"] == 1
    assert result["rank_distribution"] == {"1–3": 1, "1": 1}

@pytest.mark.parametrize("trials", [0, -1, 1001, True, 1.5])
def test_invalid_trials(trials):
    obs = position().observe(0)
    with pytest.raises(ValueError):
        BranchJobs().submit(obs, {}, obs.hand[:1], ("Random",)*3, trials, 1)

def test_jobs_deduplicate_timeout_failure():
    obs = position(14).observe(0)
    jobs = BranchJobs()
    job = jobs.submit(obs, {}, [obs.hand[0]]*2, ("Random",)*3, 2, 1)
    done = wait(jobs, job["id"])
    assert done["candidate_count"] == 1 and done["status"] == "completed"
    timeout = BranchJobs(timeout=-1)
    job = timeout.submit(obs, {}, obs.hand[:1], ("Random",)*3, 2, 1)
    assert wait(timeout, job["id"])["status"] == "timed_out"
    job = jobs.submit(obs, {}, obs.hand[:1], ("unknown",)*3, 2, 1)
    assert wait(jobs, job["id"])["status"] == "failed"

def test_cancel_and_concurrency(monkeypatch):
    import strategy_arena.branch_simulation as module
    def slow(*args):
        check = args[-2]
        while True:
            sleep(.005)
            check()
    monkeypatch.setattr(module, "simulate", slow)
    obs = position().observe(0)
    jobs = BranchJobs()
    job = jobs.submit(obs, {}, obs.hand[:1], ("Random",)*3, 2, 1)
    with pytest.raises(RuntimeError):
        jobs.submit(obs, {}, obs.hand[:1], ("Random",)*3, 2, 1)
    jobs.cancel(job["id"])
    assert wait(jobs, job["id"])["status"] == "cancelled"

def test_api_validation_history_and_state_protection(tmp_path):
    with TestClient(create_app(tmp_path / "test.sqlite")) as client:
        created = client.post("/api/games", json={}).json()
        identifier = created["id"]
        before = client.get(f"/api/games/{identifier}").json()
        card = before["observation"]["hand"][0]
        config = {"cards": [card], "strategies": ["Random"]*3, "trials": 2, "seed": 3, "turn": 0}
        response = client.post(f"/api/games/{identifier}/branches", json=config)
        assert response.status_code == 202
        jobid = response.json()["id"]
        for _ in range(300):
            job = client.get(f"/api/branches/{jobid}").json()
            if job["status"] != "running":
                break
            sleep(.01)
        assert job["status"] == "completed"
        assert job["result"]["position"]["observation"] == before["observation"]
        assert client.get(f"/api/games/{identifier}").json() == before
        assert client.post(f"/api/games/{identifier}/branches", json={**config, "trials": 0}).status_code == 422
        assert client.post(f"/api/games/{identifier}/branches", json={**config, "player": 1}).status_code == 403
        assert client.post(f"/api/games/{identifier}/branches", json={**config, "strategies": ["missing"]*3}).status_code == 422
        assert client.get("/api/branches/missing").status_code == 404
        client.post(f"/api/games/{identifier}/step")
        response = client.post(f"/api/games/{identifier}/branches", json=config)
        assert response.status_code == 202

def test_tied_final_scores_follow_engine_winners():
    from strategy_arena.game.rules import median_players
    obs = position(14).observe(0)
    for seed in range(5):
        world = sampled_game(obs, Random(__import__("strategy_arena.experiments.runner", fromlist=["derived_seed"]).derived_seed(seed, "branch-world:0")))
        card = obs.hand[0]
        world.play((card, world.observe(1).hand[0], world.observe(2).hand[0]))
        totals = world.observe(0).game_scores
        result = simulate(obs, {}, (card,), (Recorder.name,)*3, 1, seed)["candidates"][0]
        assert result["wins"] == int(0 in median_players(totals))
        assert result["average_score"] == totals[0]
        if len(set(totals)) < 3:
            assert any("–" in rank for rank in result["rank_distribution"]) == (totals.count(totals[0]) > 1)

def test_illegal_card_and_budget_rejected():
    from strategy_arena.game.cards import deck
    obs = position().observe(0)
    manager = BranchJobs()
    illegal = next(c for c in deck() if c not in obs.hand)
    with pytest.raises(ValueError):
        manager.submit(obs, {}, (illegal,), ("Random",)*3, 1, 1)
    obs = Game(42).observe(0)
    with pytest.raises(ValueError):
        manager.submit(obs, {}, obs.hand, ("Random",)*3, 1000, 1)

