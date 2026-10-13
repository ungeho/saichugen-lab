from itertools import combinations

import pytest

from strategy_arena.game.cards import Card, deal, deck
from strategy_arena.game.rules import median_players, round_awards, turn_winner


def test_deal_conserves_all_cards_and_is_reproducible():
    for seed in range(100):
        hands, unused = deal(seed)
        assert [len(hand) for hand in hands] == [17, 17, 17]
        assert set(card for hand in hands for card in hand) | {unused} == set(deck())
        assert deal(seed) == (hands, unused)


def test_complete_card_order():
    cards = deck()
    assert len(set(cards)) == 52
    assert sorted(cards) == list(cards)
    assert Card(13, 0) > Card(12, 3)
    assert Card(1, 0) < Card(2, 0)
    assert Card(7, 3) > Card(7, 2) > Card(7, 1) > Card(7, 0)


def test_every_three_card_combination_has_unique_middle():
    for low, middle, high in combinations(deck(), 3):
        assert turn_winner((high, low, middle)) == 2


@pytest.mark.parametrize("scores,winners,awards", [
    ((1, 8, 3), (2,), (0, 0, 3)),
    ((8, 8, 3), (0, 1), (8, 8, 0)),
    ((1, 8, 1), (0, 2), (1, 0, 1)),
    ((4, 4, 4), (0, 1, 2), (4, 4, 4)),
    ((0, 0, 12), (0, 1), (0, 0, 0)),
])
def test_ties_at_median(scores, winners, awards):
    assert median_players(scores) == winners
    assert round_awards(scores) == awards


def test_invalid_cards():
    for rank, suit in [(0, 0), (14, 1), (1, 4), (True, 0)]:
        with pytest.raises(ValueError):
            Card(rank, suit)
    with pytest.raises(ValueError):
        turn_winner((Card(1, 0),) * 3)
