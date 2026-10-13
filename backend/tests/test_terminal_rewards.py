from itertools import combinations
from copy import deepcopy
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient
from strategy_arena.api.app import create_app
from strategy_arena.game.rewards import terminal_rewards, REWARD_VERSION
from strategy_arena.game.rules import RULE_VERSION
from strategy_arena.experiments.runner import run_experiment
from strategy_arena.experiments.metrics import summarize
from strategy_arena.experiments.evaluation import evaluated_result, enrich_payload
from strategy_arena.experiments.catalog_statistics import algorithm_statistics
from strategy_arena.experiments.storage import ExperimentStore
from strategy_arena.branch_simulation import simulate, paired_reward_statistics
from strategy_arena.game.engine import Game


@pytest.mark.parametrize("winners,expected", [
    ([0],(2,-1,-1)), ([1],(-1,2,-1)), ([2],(-1,-1,2)),
    ([0,1],(1,1,-2)), ([0,2],(1,-2,1)), ([1,2],(-2,1,1)),
    ([0,1,2],(0,0,0)),
])
def test_reward_table_and_zero_sum(winners,expected):
    before = winners.copy()
    assert terminal_rewards(winners) == expected
    assert terminal_rewards(reversed(winners)) == expected
    assert terminal_rewards(set(winners)) == expected
    assert sum(terminal_rewards(winners)) == 0
    assert winners == before

@pytest.mark.parametrize("winners", [[], None, [0,0], [-1], [3], [True], [1.0], "0", {0:"winner"}, [0,1,2,0]])
def test_invalid_winners(winners):
    with pytest.raises(ValueError):
        terminal_rewards(winners)

def row(winners,seed=1):
    return {"seed":seed,"strategies":["A","B","C"],"scores":[8,8,3],"winners":winners,
            "turn_wins":[5,5,5],"elapsed_ns":[0,0,0]}

def test_stats_win_partition_and_mean():
    result = summarize([row([0]),row([0,1],2),row([0,1,2],3)])["strategies"]
    a = result["A"]
    assert a["win_rate"] == a["sole_win_rate"]+a["joint_win_rate"] == 1
    assert a["sole_win_rate"] == pytest.approx(1/3)
    assert a["average_terminal_reward"] == 1
    assert result["B"]["average_terminal_reward"] == 0
    assert result["C"]["average_terminal_reward"] == -1
    assert a["average_score"] == 8

def test_rotated_results_have_seat_aligned_rewards():
    rows = run_experiment([1,2],("Random","Greedy","Heuristic"),True)
    for r in rows:
        assert r["terminal_rewards"] == terminal_rewards(r["winners"])
        assert r["reward_version"] == REWARD_VERSION
    metrics = summarize(rows)["strategies"]
    for name,m in metrics.items():
        values = [r["terminal_rewards"][p] for r in rows for p,n in enumerate(r["strategies"]) if n==name]
        assert m["average_terminal_reward"] == sum(values)/len(values)
        assert m["win_rate"] == pytest.approx(m["sole_win_rate"]+m["joint_win_rate"])

def test_legacy_sqlite_read_adapter_never_rewrites(tmp_path):
    path=tmp_path/"old.sqlite3"
    store=ExperimentStore(path)
    old={"rule_version":RULE_VERSION,"information_condition":"imperfect","strategy_versions":{"A":"1","B":"1","C":"1"},
         "results":[row([0,1])],"summary":summarize([row([0,1])])}
    identifier=store.save(old)
    unknown=deepcopy(old)
    unknown["results"][0].pop("winners")
    unknownid=store.save(unknown)
    raw=sqlite3.connect(path).execute("SELECT payload FROM experiments WHERE id=?",(identifier,)).fetchone()[0]
    with TestClient(create_app(path)) as client:
        data=client.get("/api/experiments/"+identifier).json()
        assert data["results"][0]["terminal_rewards"] == [1,1,-2]
        assert data["results"][0]["reward_source"] == "derived_from_winners"
        assert data["rule_version"] == RULE_VERSION
        assert data["reward_compatibility"]["derived_games"] == 1
        invalid=client.get("/api/experiments/"+unknownid).json()
        assert invalid["results"][0]["terminal_rewards"] is None
        assert invalid["summary"]["strategies"]["A"]["average_terminal_reward"] is None
    assert sqlite3.connect(path).execute("SELECT payload FROM experiments WHERE id=?",(identifier,)).fetchone()[0] == raw
    assert store.get(identifier) == old

def test_unknown_or_invalid_saved_reward_is_not_zero():
    for r,rule in [(row([0]),"unknown-rule"), ({**row([0]),"reward_version":"future"},RULE_VERSION),
                   ({**row([0]),"reward_version":REWARD_VERSION,"terminal_rewards":[0,0,0]},RULE_VERSION),
                   ({**row([0]),"winners":[]},RULE_VERSION)]:
        result=evaluated_result(r,rule)
        assert result["terminal_rewards"] is None
        assert result["reward_source"]=="unknown"
    payload=enrich_payload({"rule_version":RULE_VERSION,"results":[row([0]),{**row([0]),"reward_version":"future"}]})
    metric=payload["summary"]["strategies"]["A"]
    assert metric["average_terminal_reward"] == 2
    assert metric["reward_games"] == 1
    assert metric["reward_unknown_games"] == 1

def test_catalog_legacy_and_recorded_compatible_metrics():
    old={"rule_version":RULE_VERSION,"information_condition":"imperfect","strategy_versions":{"A":"1","B":"1","C":"1"},
         "results":[row([0,1])],"strategy_parameters":{}}
    new=deepcopy(old)
    new["results"][0].update(terminal_rewards=[2,-1,-1],reward_version=REWARD_VERSION,reward_source="recorded",winners=[0])
    group=algorithm_statistics("A",[("old",old),("new",new)])["groups"][0]
    assert group["average_terminal_reward"] == 1.5
    assert group["win_rate"] == group["sole_win_rate"]+group["joint_win_rate"] == 1
    assert group["reward_sources"] == {"derived_from_winners":1,"recorded":1}

def test_game_api_rewards_are_null_until_finished(tmp_path):
    with TestClient(create_app(tmp_path/"game.sqlite")) as client:
        game=client.post("/api/games",json={}).json()
        identifier=game["id"]
        assert game["terminal_rewards"] is None
        for _ in range(14):
            game=client.post(f"/api/games/{identifier}/step").json()
            assert game["terminal_rewards"] is None
        game=client.post(f"/api/games/{identifier}/step").json()
        assert game["terminal_rewards"] == list(terminal_rewards(game["winners"]))
        scores=game["observation"]["game_scores"]
        assert client.get(f"/api/games/{identifier}").json()["observation"]["game_scores"] == scores

def test_paired_reward_ci_and_small_samples():
    result=paired_reward_statistics([2,1,0],[-1,-2,0])
    assert result["average_terminal_reward_difference"] == 2
    assert result["reward_difference_ci95"] == pytest.approx([.04,3.96])
    assert paired_reward_statistics([2],[-1])["reward_difference_ci95"] is None
    assert paired_reward_statistics([1,1],[0,0])["reward_difference_ci95"] == [1,1]
    assert paired_reward_statistics([0,0],[0,0])["reward_difference_zero_variance"]
    with pytest.raises(ValueError):
        paired_reward_statistics([],[])
    with pytest.raises(ValueError):
        paired_reward_statistics([1],[1,2])

def test_branch_rewards_and_existing_metrics_against_manual_shared_trials():
    from random import Random
    from strategy_arena.branch_simulation import sampled_game
    from strategy_arena.experiments.runner import derived_seed
    from strategy_arena.strategies.registry import create_strategy
    game=Game(42)
    for _ in range(14):
        game.play(tuple(game.observe(p).hand[0] for p in range(3)))
    obs=game.observe(0)
    before=deepcopy(game.__dict__)
    cards=obs.hand[:2];names=("Random",)*3;count=8;seed=12
    expected=[[] for _ in cards]
    for t in range(count):
        base=sampled_game(obs,Random(derived_seed(seed,f"branch-world:{t}")))
        for index,card in enumerate(cards):
            copied=deepcopy(base)
            actions=[card]
            for p in (1,2):
                rng=Random(derived_seed(seed,f"branch-policy:{t}:{p}:Random:1"))
                actions.append(create_strategy("Random").choose(copied.observe(p),rng).card)
            copied.play(tuple(actions))
            expected[index].append((copied.observe(0).game_scores[0], copied.winners))
    result=simulate(obs,{},cards,names,count,seed)
    assert result==simulate(obs,{},cards,names,count,seed)
    for r,values in zip(result["candidates"],expected):
        assert r["average_score"] == sum(s for s,_ in values)/count
        assert r["win_rate"] == sum(0 in w for _,w in values)/count
        assert r["win_rate"] == r["sole_win_rate"]+r["joint_win_rate"]
        assert r["average_terminal_reward"] == sum(terminal_rewards(w)[0] for _,w in values)/count
    pair=result["paired"][0]
    assert pair["average_terminal_reward_difference"] == sum(terminal_rewards(a[1])[0]-terminal_rewards(b[1])[0] for a,b in zip(*expected))/count
    assert result["reward_version"]==REWARD_VERSION
    assert game.__dict__==before

def test_payload_reward_version_is_not_ignored():
    supported = {"rule_version":RULE_VERSION,"reward_version":REWARD_VERSION,
                 "results":[{**row([0]),"terminal_rewards":[2,-1,-1]}]}
    enriched=enrich_payload(supported)
    assert enriched["results"][0]["reward_source"]=="recorded"
    assert enriched["summary"]["strategies"]["A"]["average_terminal_reward"]==2
    future={"rule_version":RULE_VERSION,"reward_version":"future-reward","results":[row([0])]}
    unknown=enrich_payload(future)
    assert unknown["results"][0]["terminal_rewards"] is None
    assert unknown["summary"]["strategies"]["A"]["average_terminal_reward"] is None

def test_catalog_keeps_reward_versions_separate():
    base={"rule_version":RULE_VERSION,"information_condition":"imperfect","strategy_versions":{"A":"1","B":"1","C":"1"},
          "results":[row([0])],"strategy_parameters":{}}
    future={**deepcopy(base),"reward_version":"future-reward"}
    groups=algorithm_statistics("A",[("known",base),("future",future)])["groups"]
    assert len(groups)==2
    assert sorted(g["reward_games"] for g in groups)==[0,1]
    assert any(g["average_terminal_reward"] is None for g in groups)

def test_rule_page_uses_same_reward_function():
    from strategy_arena.rule_guide import rule_guide
    guide=rule_guide()
    assert guide["reward"]["version"]==REWARD_VERSION
    assert [(r["winner_reward"],r["loser_reward"]) for r in guide["reward"]["table"]]==[(2,-1),(1,-2),(0,0)]
    for example in guide["final_examples"]:
        assert example["terminal_rewards"]==terminal_rewards(example["winners"])

