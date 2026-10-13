"""観測だけから世界を復元する、分岐実験とRollout戦略の共通実行部分。"""
from copy import deepcopy
from random import Random
from .game.engine import Game
from .game.rewards import terminal_rewards
from .inference import UniformSampler
from .strategies.base import decide

def sampled_game(observation, rng):
    hypothesis = UniformSampler().sample(observation, rng)
    hands = [hypothesis.hands[p] + tuple(t.cards[p] for t in observation.history) for p in range(3)]
    game = Game.from_deal(hands, hypothesis.unused)
    for event in observation.history:
        if game.play(event.cards) != event:
            raise ValueError("公開履歴がルールと一致しません")
    if game.observe(observation.player) != observation:
        raise ValueError("復元した観測が一致しません")
    return game

def rollout_trial(observation, cards, templates, seed, trial, check=lambda: None, policy_names=None):
    # 実行時importによりregistry/comparison/runnerとの初期化循環を避ける。
    from .comparison import clone_strategy
    from .experiments.runner import derived_seed
    names = policy_names if policy_names is not None else [s.name for s in templates]
    versions = [s.version for s in templates]
    rows = []
    base = sampled_game(observation, Random(derived_seed(seed, f"branch-world:{trial}")))
    rng_states = [Random(derived_seed(seed, f"branch-policy:{trial}:{p}:{names[p]}:{versions[p]}")).getstate() for p in range(3)]
    for card in cards:
        check()
        game = deepcopy(base)
        policies = [clone_strategy(s) for s in templates]
        rngs = [Random() for _ in range(3)]
        for rng, state in zip(rngs, rng_states):
            rng.setstate(state)
        first = True
        while not game.finished:
            check()
            observations = [game.observe(p) for p in range(3)]
            actions = []
            for p in range(3):
                actions.append(card if first and p == observation.player else decide(policies[p], observations[p], rngs[p], False).card)
                check()
            game.play(tuple(actions))
            first = False
        scores = game.observe(observation.player).game_scores
        score = scores[observation.player]
        best = 1 + sum(s > score for s in scores)
        worst = 3 - sum(s < score for s in scores)
        rank = str(best) if best == worst else f"{best}–{worst}"
        winners = game.winners
        won = observation.player in winners
        rows.append({"score": score, "win": int(won), "rank": rank,
                                "sole_win": int(won and len(winners) == 1),
                                "joint_win": int(won and len(winners) > 1),
                                "reward": terminal_rewards(winners)[observation.player]})
    return rows
