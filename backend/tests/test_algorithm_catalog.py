from dataclasses import replace
import json
from pathlib import Path
from random import Random

from fastapi.testclient import TestClient
import pytest

from strategy_arena.api.app import create_app
from strategy_arena.game.engine import Game
from strategy_arena.strategies.base import Decision, decide
from strategy_arena.strategies.baselines import Baseline, NAMES
from strategy_arena.strategies.descriptions import AlgorithmDescription
from strategy_arena.strategies.registry import register, algorithm_catalog
from strategy_arena.experiments.runner import run_game, run_experiment
from strategy_arena.experiments.storage import ExperimentStore
from strategy_arena.experiments.catalog_statistics import algorithm_statistics


@pytest.mark.parametrize("name", NAMES)
def test_capture_does_not_change_choices_or_rng(name):
    observation = Game(4).observe(1)
    plain_rng, detailed_rng = Random(42), Random(42)
    plain = decide(Baseline(name), observation, plain_rng)
    detailed = decide(Baseline(name), observation, detailed_rng, True)
    assert plain.card == detailed.card
    assert plain_rng.getstate() == detailed_rng.getstate()
    assert plain.details is None
    assert detailed.details is not None
    assert {c.card for c in detailed.details.candidates} == set(observation.legal_actions)
    if name == "Random":
        assert all(c.score is None for c in detailed.details.candidates)
    else:
        selected = next(c for c in detailed.details.candidates if c.card == detailed.card)
        assert selected.score == max(c.score for c in detailed.details.candidates)
        for candidate in detailed.details.candidates:
            parts = candidate.components
            if name == "Heuristic":
                assert candidate.score == parts["win_term"] + parts["distance_term"] + parts["hand_term"]
            else:
                assert candidate.score == parts["desire"] * parts["turn_win_probability"]


def test_v1_actions_unchanged():
    records = json.loads((Path(__file__).parent / "fixtures/baseline_v1.json").read_text())
    for record in records:
        for capture in (False, True):
            game, trace = run_game(record["seed"], (record["name"],) * 3, capture_details=capture)
            assert [[d["card"] for d in t["decisions"]] for t in trace] == record["actions"]
            assert list(game.observe(0).game_scores) == record["scores"]


def test_score_aware_and_game_score_override_are_recorded():
    observation = replace(Game(1).observe(0), round_scores=(8, 3, 1))
    aware = Baseline("ScoreAware").choose_detailed(observation, Random(1))
    assert aware.desire_to_win == -1
    assert "このターンは獲得を避けます。" in aware.details.reasoning
    for candidate in aware.details.candidates:
        assert candidate.score == -candidate.components["turn_win_probability"]
    observation = replace(observation, round_scores=(0, 0, 0), game_scores=(20, 10, 1))
    heuristic = Baseline("Heuristic").choose_detailed(observation, Random(1))
    assert heuristic.desire_to_win == -1
    assert "(20, 10, 1)" in " ".join(heuristic.details.reasoning)


def test_old_strategy_and_missing_description_are_supported(tmp_path):
    class OldStyle:
        name = "OldStyleCatalogTest"
        version = "old-1"
        def choose(self, observation, rng):
            return Decision(observation.hand[0])
    register(OldStyle.name, OldStyle)
    result = decide(OldStyle(), Game(1).observe(0), Random(1), True)
    assert result.details is None
    catalog = {r["name"]: r for r in algorithm_catalog()}
    assert catalog[OldStyle.name]["description_available"] is False
    client = TestClient(create_app(tmp_path / "catalog.sqlite3"))
    game = client.post("/api/games", json={"strategies": [OldStyle.name] * 3}).json()
    step = client.post(f"/api/games/{game['id']}/step").json()
    assert step["decisions"][0][0]["details_status"] == "not_provided"
    assert step["decisions"][0][0]["explanation"] == ""


def test_optional_registration_description():
    class WithDescription:
        name = "DescribedCatalogTest"
        version = "2"
        def choose(self, observation, rng):
            return Decision(observation.hand[0])
    register(WithDescription.name, WithDescription, AlgorithmDescription(tagline="登録と一緒に説明"))
    entry = next(r for r in algorithm_catalog() if r["name"] == WithDescription.name)
    assert entry["tagline"] == "登録と一緒に説明"
    assert entry["version"] == "2"


def test_batch_default_has_no_detailed_recording(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("バッチで詳細ログが呼ばれました")
    monkeypatch.setattr(Baseline, "choose_detailed", forbidden)
    monkeypatch.setattr("strategy_arena.experiments.runner.decision_record", forbidden)
    rows = run_experiment([1], ("Random", "Greedy", "Heuristic"))
    assert all("decision_trace" not in row for row in rows)


def test_batch_details_are_opt_in():
    rows = run_experiment([1], ("Random", "Greedy", "Heuristic"), rotate=False, capture_details=True)
    assert len(rows[0]["decision_trace"]) == 15
    assert rows[0]["decision_trace"][0]["decisions"][0]["details_status"] == "available"
    plain = run_experiment([1], ("Random", "Greedy", "Heuristic"), rotate=False)
    assert [{k: v for k, v in row.items() if k not in ("decision_trace", "elapsed_ns")} for row in rows] == [
        {k: v for k, v in row.items() if k != "elapsed_ns"} for row in plain]


def test_api_capture_visibility_and_turn_context(tmp_path):
    client = TestClient(create_app(tmp_path / "catalog.sqlite3"))
    initial = client.post("/api/games", json={}).json()
    identifier = initial["id"]
    first = client.post(f"/api/games/{identifier}/step").json()
    assert first["decisions"][0][0]["context"]["round_scores"] == [0, 0, 0]
    assert first["decisions"][0][0]["details"]["candidates"][0]["score"] is None
    assert first["decisions"][0][1]["details_status"] == "hidden"
    assert "details" not in first["decisions"][0][1]
    assert client.get(f"/api/games/{identifier}?analysis=true").json()["analysis_visible"] is False
    for _ in range(14):
        client.post(f"/api/games/{identifier}/step")
    completed = client.get(f"/api/games/{identifier}?analysis=true").json()
    assert completed["analysis_visible"]
    assert completed["decisions"][0][1]["details_status"] == "available"
    assert completed["decisions"][1][0]["context"]["public_history_length"] == 1
    assert client.get(f"/api/games/{identifier}").json()["decisions"][0][1]["details_status"] == "hidden"
    disabled = client.post("/api/games", json={"capture_details": False}).json()
    disabled = client.post(f"/api/games/{disabled['id']}/step").json()
    assert disabled["decisions"][0][0]["details_status"] == "disabled"
    assert "context" not in disabled["decisions"][0][0]


def test_catalog_statistics_separate_conditions_and_legacy(tmp_path):
    client = TestClient(create_app(tmp_path / "catalog.sqlite3"))
    store = ExperimentStore(tmp_path / "catalog.sqlite3")
    assert client.get("/api/algorithms/Random/statistics").json()["groups"] == []
    assert client.get("/api/algorithms/Missing/statistics").status_code == 404
    catalog = client.get("/api/algorithms").json()
    assert all(next(r for r in catalog if r["name"] == n)["description_available"] for n in NAMES)
    def save(rule="r1", condition="imperfect", version="1", opponent="B"):
        payload = {"rule_version": rule, "information_condition": condition,
                   "strategy_versions": {"Random": version, opponent: "1", "C": "1"},
                   "results": [{"strategies": ["Random", opponent, "C"], "scores": [7, 8, 6], "winners": [0]}]}
        store.save(payload)
    save(); save(); save(rule="r2"); save(condition="full"); save(version="2"); save(opponent="D")
    store.save({"results": []})
    data = client.get("/api/algorithms/Random/statistics").json()
    assert len(data["groups"]) == 5
    assert data["unclassified_experiments"] == 1
    first = data["groups"][0]
    assert first["participations"] == first["match_count"] == 2
    assert first["win_rate"] == 1
    assert first["average_score"] == 7
    assert first["score_distribution"] == [{"score": 7, "count": 2}]


def test_statistics_opponent_versions_settings_and_duplicate_seats():
    payload = {"rule_version": "r", "information_condition": "imperfect",
               "strategy_versions": {"A": "1", "B": "1"},
               "results": [{"strategies": ["A", "A", "B"], "scores": [5, 5, 10], "winners": [0, 1]}]}
    changed_opponent = {**payload, "strategy_versions": {"A": "1", "B": "2"}}
    recorded_defaults = {**payload, "strategy_parameters": {}}
    data = algorithm_statistics("A", [("one", payload), ("two", changed_opponent), ("three", recorded_defaults)])
    assert len(data["groups"]) == 3
    assert all(g["participations"] == 2 and g["match_count"] == 1 for g in data["groups"])
    assert all(g["wins"] == 2 and g["average_score"] == 5 for g in data["groups"])
