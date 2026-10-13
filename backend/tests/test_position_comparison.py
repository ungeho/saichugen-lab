from copy import deepcopy
from dataclasses import fields
from random import Random
from threading import Lock

from fastapi.testclient import TestClient
import pytest

from strategy_arena.api.app import create_app
from strategy_arena.comparison import compare_position, initial_strategy_copies, position_at
from strategy_arena.experiments.runner import derived_seed
from strategy_arena.game.engine import Game
from strategy_arena.research.replay import export_full
from strategy_arena.strategies.base import Decision, decide
from strategy_arena.strategies.baselines import Baseline, NAMES
from strategy_arena.strategies.registry import register, algorithm_catalog


class Stateful:
    name = "ComparisonStateful"
    version = "trained-7"
    def __init__(self):
        self.calls = 0
        self.learned_offset = 7
    def choose(self, observation, rng):
        self.calls += 1
        return Decision(observation.hand[(self.learned_offset + self.calls) % len(observation.hand)])


register(Stateful.name, Stateful)


def make_session():
    instances = [Stateful(), Baseline("Greedy"), Baseline("Random")]
    rngs = [Random(derived_seed(42, str(p))) for p in range(3)]
    return {"game": Game(42), "names": (Stateful.name, "Greedy", "Random"),
            "strategies": instances, "comparison_initial_strategies": initial_strategy_copies(instances),
            "rngs": rngs, "initial_rng_states": [rng.getstate() for rng in rngs],
            "capture_details": True, "human_turns": []}


def advance(session, human=False):
    game = session["game"]
    observations = [game.observe(p) for p in range(3)]
    decisions = [Decision(obs.hand[0]) if p == 0 and human else decide(s, obs, rng, True)
                 for p, (s, obs, rng) in enumerate(zip(session["strategies"], observations, session["rngs"]))]
    game.play(tuple(d.card for d in decisions))
    session["human_turns"].append(human)


def without_time(result):
    result = deepcopy(result)
    for row in result["results"]:
        row.pop("elapsed_ns")
    return result


def test_same_observation_and_no_hidden_state():
    seen = []
    class Recorder:
        name = "ComparisonRecorderA"
        version = "1"
        def choose(self, observation, rng):
            seen.append(observation)
            return Decision(observation.hand[0])
    class RecorderB(Recorder):
        name = "ComparisonRecorderB"
    register(Recorder.name, Recorder)
    register(RecorderB.name, RecorderB)
    session = make_session()
    result = compare_position(session, [Recorder.name, RecorderB.name], 42)
    assert seen[0] is seen[1]
    assert {f.name for f in fields(seen[0])} == {
        "player", "hand", "history", "round_scores", "game_scores", "turn", "hand_sizes"}
    assert seen[0].hand == session["game"].observe(0).hand
    assert not hasattr(seen[0], "seed") and not hasattr(seen[0], "_unused")
    assert all(r["decision"]["details_status"] == "not_provided" for r in result["results"])
    assert all(r["state_source"] == "registered_initial_copy" for r in result["results"])
    assert RecorderB.name in [a["name"] for a in algorithm_catalog()]


def test_live_and_historical_internal_state_and_learned_values_are_preserved():
    session = make_session()
    for _ in range(3):
        advance(session)
    before = export_full(session["game"])
    rng_states = [rng.getstate() for rng in session["rngs"]]
    live = compare_position(session, [Stateful.name], 4)
    observation = session["game"].observe(0)
    expected = observation.hand[(7 + 4) % len(observation.hand)]
    assert live["results"][0]["decision"]["card"] == {"rank": expected.rank, "suit": expected.suit}
    assert live["results"][0]["state_source"] == "live_copy"
    past = compare_position(session, [Stateful.name], 4, turn=1)
    past_observation, _ = position_at(session["game"], 1, 0)
    expected = past_observation.hand[(7 + 2) % len(past_observation.hand)]
    assert past["results"][0]["decision"]["card"] == {"rank": expected.rank, "suit": expected.suit}
    assert past["results"][0]["state_source"] == "history_reconstructed"
    assert session["strategies"][0].calls == 3
    assert session["strategies"][0].learned_offset == 7
    assert export_full(session["game"]) == before
    assert [rng.getstate() for rng in session["rngs"]] == rng_states
    assert session["comparison_initial_strategies"][0].calls == 0


def test_history_reconstruction_skips_human_actions():
    session = make_session()
    advance(session, human=True)
    advance(session)
    past = compare_position(session, [Stateful.name], 1, turn=1)
    obs, _ = position_at(session["game"], 1, 0)
    expected = obs.hand[(7 + 1) % len(obs.hand)]
    assert past["results"][0]["decision"]["card"] == {"rank": expected.rank, "suit": expected.suit}
    assert session["strategies"][0].calls == 1


def test_comparison_does_not_change_following_game_actions():
    compared, control = make_session(), make_session()
    advance(compared); advance(control)
    compare_position(compared, list(NAMES) + [Stateful.name], 42)
    for _ in range(4):
        advance(compared); advance(control)
    assert export_full(compared["game"]) == export_full(control["game"])


def test_reproducibility_and_selection_order_independent_rngs():
    session = make_session()
    first = compare_position(session, list(NAMES), 42)
    second = compare_position(session, list(NAMES), 42)
    assert without_time(first) == without_time(second)
    reverse = compare_position(session, list(reversed(NAMES)), 42)
    assert {r["name"]: r["decision"] for r in first["results"]} == {r["name"]: r["decision"] for r in reverse["results"]}
    selections = {str(compare_position(session, ["Random"], seed)["results"][0]["decision"]["card"]) for seed in range(20)}
    assert len(selections) > 1
    assert len({r["derived_seed"] for r in first["results"]}) == len(NAMES)


def test_noncopyable_strategy_is_reported_without_resetting_or_stopping_others():
    class Noncopyable:
        name = "ComparisonNoncopyable"
        version = "1"
        def __init__(self):
            self.lock = Lock()
        def choose(self, observation, rng):
            return Decision(observation.hand[0])
    register(Noncopyable.name, Noncopyable)
    result = compare_position(make_session(), [Noncopyable.name, "Random"], 1)
    assert result["results"][0]["status"] == "error"
    assert "複製できません" in result["results"][0]["error"]
    assert result["results"][1]["status"] == "ok"


def test_custom_clone_hook_and_invalid_actions():
    class HookStrategy:
        name = "ComparisonCloneHook"
        version = "1"
        def __init__(self, weight=11):
            self.lock = Lock()
            self.weight = weight
        def clone_for_comparison(self):
            return HookStrategy(self.weight)
        def choose(self, observation, rng):
            return Decision(observation.hand[self.weight % len(observation.hand)])
    class BadAction:
        name = "ComparisonBadAction"
        version = "1"
        def choose(self, observation, rng):
            from strategy_arena.game.cards import Card
            return Decision(next(c for c in observation.unseen_cards if c not in observation.hand))
    register(HookStrategy.name, HookStrategy)
    register(BadAction.name, BadAction)
    result = compare_position(make_session(), [HookStrategy.name, BadAction.name], 1)
    assert result["results"][0]["status"] == "ok"
    assert result["results"][1]["status"] == "error"


def test_other_seat_private_state_is_not_used_for_target_player():
    class OtherSeat:
        name = "ComparisonOtherSeat"
        version = "1"
        def __init__(self):
            self.private_offset = 0
        def choose(self, observation, rng):
            return Decision(observation.hand[self.private_offset % len(observation.hand)])
    register(OtherSeat.name, OtherSeat)
    session = make_session()
    session["names"] = (Stateful.name, OtherSeat.name, "Random")
    session["strategies"][1] = OtherSeat()
    session["strategies"][1].private_offset = 10
    result = compare_position(session, [OtherSeat.name], 42, player=0)
    expected = session["game"].observe(0).hand[0]
    assert result["results"][0]["decision"]["card"] == {"rank": expected.rank, "suit": expected.suit}
    assert result["results"][0]["state_source"] == "registered_initial_copy"
    assert session["strategies"][1].private_offset == 10


def test_history_mismatch_is_not_silently_replaced_with_fresh_state():
    session = make_session()
    advance(session); advance(session)
    session["comparison_initial_strategies"][0].learned_offset = 99
    result = compare_position(session, [Stateful.name, "Random"], 1, turn=1)
    assert result["results"][0]["status"] == "error"
    assert "一致しません" in result["results"][0]["error"]
    assert result["results"][1]["status"] == "ok"
    assert session["strategies"][0].calls == 2


def test_api_positions_past_snapshot_and_nonmutation(tmp_path):
    client = TestClient(create_app(tmp_path / "positions.sqlite3"))
    identifier = client.post("/api/games", json={}).json()["id"]
    initial = client.get(f"/api/games/{identifier}").json()
    body = {"strategies": list(NAMES), "seed": 42, "turn": 0}
    compared = client.post(f"/api/games/{identifier}/compare", json=body)
    assert compared.status_code == 200
    assert client.get(f"/api/games/{identifier}").json() == initial
    assert compared.json()["position"]["observation"]["hand"] == initial["observation"]["hand"]
    for _ in range(4):
        client.post(f"/api/games/{identifier}/step")
    before = client.get(f"/api/games/{identifier}").json()
    old = client.get(f"/api/games/{identifier}/comparison-position?turn=0").json()
    assert old["snapshot_id"] == compared.json()["position"]["snapshot_id"]
    assert old["observation"]["history"] == []
    assert old["observation"]["round_scores"] == [0, 0, 0]
    repeated = client.post(f"/api/games/{identifier}/compare", json=body).json()
    # 状態の出所はliveからhistoryへ変わるが、同じ判断が得られる。
    assert [r["decision"] for r in repeated["results"]] == [r["decision"] for r in compared.json()["results"]]
    assert client.get(f"/api/games/{identifier}").json() == before
    assert "initial_hands" not in str(repeated) and "unused" not in str(repeated)
    assert client.get(f"/api/games/{identifier}/comparison-position?turn=10").status_code == 409


def test_api_validation_and_other_player_view_requires_finished_analysis(tmp_path):
    client = TestClient(create_app(tmp_path / "positions.sqlite3"))
    identifier = client.post("/api/games", json={}).json()["id"]
    endpoint = f"/api/games/{identifier}/compare"
    for strategies in ([], ["Missing"], ["Random", "Random"]):
        assert client.post(endpoint, json={"strategies": strategies}).status_code == 422
    assert client.post(endpoint, json={"strategies": ["Random"], "information_condition": "full"}).status_code == 422
    assert client.post(endpoint, json={"strategies": ["Random"], "player": 1, "analysis": True}).status_code == 403
    for _ in range(15):
        client.post(f"/api/games/{identifier}/step")
    assert client.get(f"/api/games/{identifier}/comparison-position?player=1&turn=14").status_code == 403
    response = client.post(endpoint, json={"strategies": list(NAMES), "player": 1, "turn": 14, "analysis": True})
    assert response.status_code == 200
    assert len(response.json()["position"]["observation"]["hand"]) == 3
    assert all(r["status"] == "ok" for r in response.json()["results"])
