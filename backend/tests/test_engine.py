from dataclasses import fields, FrozenInstanceError
from itertools import combinations
from random import Random

import pytest

from strategy_arena.game.engine import Game
from strategy_arena.game.cards import deck
from strategy_arena.inference import UniformSampler
from strategy_arena.research.replay import export_full, replay


def test_full_games_and_replays():
    for seed in range(50):
        game = Game(seed)
        rng = Random(seed)
        for turn in range(15):
            event = game.play(tuple(rng.choice(game.observe(p).legal_actions) for p in range(3)))
            assert sum(event.round_scores) >= event.cards[event.winner].rank
            if (turn + 1) % 3 == 0:
                assert game.observe(0).round_scores == (0, 0, 0)
            assert replay(export_full(game)).observe(0) == game.observe(0)
        assert game.finished and game.winners
        assert game.observe(0).hand_sizes == (2, 2, 2)
        assert not game.observe(0).legal_actions
        before = export_full(game)
        with pytest.raises(ValueError):
            game.play(tuple(game.observe(p).hand[0] for p in range(3)))
        assert export_full(game) == before


def test_round_scoring_against_independent_history_calculation():
    game = Game(10)
    totals = [0, 0, 0]
    round_scores = [0, 0, 0]
    for i in range(15):
        actions = tuple(game.observe(p).hand[0] for p in range(3))
        event = game.play(actions)
        middle_card = sorted(actions)[1]
        round_scores[actions.index(middle_card)] += middle_card.rank
        if i % 3 == 2:
            median = sorted(round_scores)[1]
            totals = [totals[p] + (v if v == median else 0) for p, v in enumerate(round_scores)]
            round_scores = [0, 0, 0]
        assert event.game_scores == tuple(totals)


def test_invalid_action_is_atomic():
    game = Game(1)
    before = export_full(game)
    actions = tuple(game.observe(p).hand[0] for p in range(3))
    with pytest.raises(ValueError):
        game.play((actions[1], actions[1], actions[2]))
    assert export_full(game) == before


def test_observation_has_no_hidden_state_and_is_immutable():
    game = Game(1)
    obs = game.observe(0)
    assert {f.name for f in fields(obs)} == {
        "player", "hand", "history", "round_scores", "game_scores", "turn", "hand_sizes"}
    with pytest.raises(FrozenInstanceError):
        obs.turn = 4
    original = export_full(game)
    swapped = export_full(game)
    swapped["initial_hands"][1], swapped["initial_hands"][2] = swapped["initial_hands"][2], swapped["initial_hands"][1]
    assert replay(swapped).observe(0) == replay(original).observe(0)


def test_counting_and_hypotheses_at_every_turn():
    game = Game(12)
    sampler = UniformSampler()
    for turn in range(16):
        for p in range(3):
            obs = game.observe(p)
            assert len(obs.unseen_cards) == 35 - 2 * turn
            h = sampler.sample(obs, Random(123))
            assert h == sampler.sample(obs, Random(123))
            assert h.hands[p] == obs.hand
            unknown_hands = [set(h.hands[q]) for q in range(3) if q != p]
            assert not unknown_hands[0] & unknown_hands[1]
            assert set.union(*unknown_hands, {h.unused}) == set(obs.unseen_cards)
            assert all(len(hand) == 17 - turn for hand in h.hands)
            assert len(obs.actions_by(p)) == turn
        if turn < 15:
            game.play(tuple(game.observe(p).hand[0] for p in range(3)))
