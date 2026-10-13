from fastapi.testclient import TestClient

from strategy_arena.api.app import create_app


def test_health(tmp_path):
    client = TestClient(create_app(tmp_path / "experiments.sqlite3"))
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_human_and_auto_game_and_public_boundary(tmp_path):
    client = TestClient(create_app(tmp_path / "experiments.sqlite3"))
    created = client.post("/api/games", json={}).json()
    identifier = created["id"]
    assert "unused" not in str(created)
    assert "initial_hands" not in str(created)
    obs = created["observation"]
    card = obs["hand"][0]
    response = client.post(f"/api/games/{identifier}/actions", json={**card, "turn": 0})
    assert response.status_code == 200
    before = client.get(f"/api/games/{identifier}").json()
    assert client.post(f"/api/games/{identifier}/actions", json={**card, "turn": 0}).status_code == 409
    assert client.get(f"/api/games/{identifier}").json() == before
    for _ in range(14):
        response = client.post(f"/api/games/{identifier}/step")
        assert response.status_code == 200
    data = response.json()
    assert data["finished"]
    assert data["observation"]["hand_sizes"] == [2, 2, 2]
    assert len(data["observation"]["history"]) == 15
    assert client.post(f"/api/games/{identifier}/step").status_code == 409


def test_experiment_save_and_reproduce(tmp_path):
    client = TestClient(create_app(tmp_path / "experiments.sqlite3"))
    config = {"seed": 2, "deals": 2, "strategies": ["Random", "Greedy", "Heuristic"]}
    result = client.post("/api/experiments", json=config).json()
    assert result["summary"]["games"] == 12
    assert result["information_condition"] == "imperfect"
    assert client.get(f"/api/experiments/{result['id']}").json() == result
    repeated = client.post("/api/experiments", json=config).json()
    def without_time(rows):
        return [{k: v for k, v in row.items() if k != "elapsed_ns"} for row in rows]
    assert without_time(result["results"]) == without_time(repeated["results"])
    assert client.post("/api/games", json={"strategies": ["Bad"] * 3}).status_code == 422


def test_no_research_route(tmp_path):
    client = TestClient(create_app(tmp_path / "experiments.sqlite3"))
    routes = {r.path for r in client.app.routes}
    assert not any("research" in path or "replay" in path for path in routes)
