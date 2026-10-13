from itertools import permutations
from dataclasses import asdict
import pytest
from fastapi.testclient import TestClient
from strategy_arena.api.app import create_app
from strategy_arena.game.cards import Card, deck
from strategy_arena.game.engine import Game
from strategy_arena.game.rules import RULE_VERSION, TURNS_PER_ROUND, ROUNDS_PER_GAME, turn_winner, median_players, round_awards
from strategy_arena.rule_guide import rule_guide, judge

def test_displayed_constants_and_comparison_match_engine():
    guide = rule_guide()
    game = Game(42)
    obs = game.observe(0)
    assert guide["rule_version"] == RULE_VERSION
    assert guide["constants"] == {
        "players": len(obs.hand_sizes), "cards": len(deck()), "initial_hand": len(obs.hand),
        "unused": 1, "turns_per_round": TURNS_PER_ROUND, "rounds": ROUNDS_PER_GAME,
        "turns": 15, "remaining_hand": 2}
    assert guide["rank_order"] == list(range(13, 0, -1))
    assert guide["suit_order"] == [3, 2, 1, 0]
    assert Card(13, 0) > Card(12, 3)
    for _ in range(15):
        assert game.observe(0).legal_actions == game.observe(0).hand
        game.play(tuple(game.observe(p).hand[0] for p in range(3)))
    assert game.finished
    assert game.observe(0).hand_sizes == (2, 2, 2)
    assert game.observe(0).legal_actions == ()

@pytest.mark.parametrize("cards,winner,delta", [
    ((Card(2,3), Card(8,0), Card(13,2)),1,(0,8,0)),
    ((Card(7,3), Card(7,0), Card(7,2)),2,(0,0,7)),
    ((Card(7,1), Card(7,0), Card(7,2)),0,(7,0,0)),
    ((Card(1,3), Card(10,3), Card(13,3)),1,(0,10,0)),
    ((Card(8,0), Card(7,3), Card(9,1)),0,(8,0,0)),
])
def test_published_card_examples(cards,winner,delta):
    result = judge(cards)
    assert result["winner"] == winner
    assert result["round_delta"] == delta
    assert result["game_delta"] == (0,0,0)
    assert cards[result["weak_to_strong"][1]] == cards[winner]

def test_suit_ties_in_any_submission_order():
    for rank in (1, 7, 13):
        for cards in permutations((Card(rank,3),Card(rank,1),Card(rank,0))):
            result = judge(cards)
            assert cards[result["winner"]] == Card(rank,1)
            assert result["round_delta"][result["winner"]] == rank

def test_round_examples_are_actual_three_turn_games():
    first, zero = rule_guide()["round_examples"]
    assert first["round_scores"] == (8,8,3)
    assert first["winners"] == (0,1)
    assert first["game_delta"] == (8,8,0)
    assert zero["round_scores"] == (0,0,12)
    assert zero["winners"] == (0,1)
    assert zero["game_delta"] == (0,0,0)
    for example in (first,zero):
        assert len(example["turns"]) == TURNS_PER_ROUND
        assert example["next_round_scores"] == (0,0,0)
        assert example["game_delta"] == round_awards(example["round_scores"])
        for event in example["turns"]:
            assert turn_winner(tuple(Card(**c) for c in event["cards"])) == event["winner"]

def test_final_examples_and_provenance():
    guide = rule_guide()
    assert [r["winners"] for r in guide["final_examples"]] == [(1,),(0,1),(0,1),(0,1,2)]
    sources = {s["id"] for s in guide["sources"]}
    assert all(r["source"] in sources for r in guide["rules"])
    by_id = {r["id"]:r for r in guide["rules"]}
    assert by_id["order"]["source"] == "secondary"
    assert by_id["values"]["source"] == "secondary"
    assert by_id["visibility"]["source"] == "approved"
    assert by_id["final_storage"]["source"] == "implementation"
    assert any("原典全文との一致は未確認" in s for s in guide["uncertainties"])

def test_rules_api_validation_and_no_game_mutation(tmp_path):
    with TestClient(create_app(tmp_path/"test.sqlite3")) as client:
        created = client.post("/api/games",json={}).json()
        identifier = created["id"]
        before = client.get(f"/api/games/{identifier}").json()
        guide = client.get("/api/rules")
        assert guide.status_code == 200
        for example in guide.json()["turn_examples"]:
            result = client.post("/api/rules/judge", json={"cards":example["cards"]})
            assert result.status_code == 200
            assert result.json()["winner"] == example["winner"]
            assert result.json()["round_delta"] == example["round_delta"]
        for cards in ([{"rank":1,"suit":0}]*3, [{"rank":14,"suit":0}]*3, [],
                      [{"rank":True,"suit":0},{"rank":7,"suit":1},{"rank":13,"suit":3}]):
            assert client.post("/api/rules/judge",json={"cards":cards}).status_code == 422
        assert client.get(f"/api/games/{identifier}").json() == before

