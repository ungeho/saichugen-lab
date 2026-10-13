"""比較条件の照合と、小標本を確実と見せない配札単位の推定。"""
from collections import defaultdict
from itertools import permutations
import numpy as np

from ..game.rewards import terminal_rewards

MIN_CI_DEALS = 10
ROTATIONS = tuple(permutations(range(3)))


def uncertainty(values, seed):
    n = len(values)
    if n < MIN_CI_DEALS:
        return {"ci95": None, "status": "insufficient_deals", "independent_deals": n,
                "reason": f"独立配札{n}件。{MIN_CI_DEALS}件未満のため区間を表示しません。点推定も暫定です。"}
    if len(set(values)) == 1:
        return {"ci95": None, "status": "zero_variance", "independent_deals": n,
                "reason": "標本の配札平均・対応差がすべて同じです。0幅を確実性と誤認しないよう区間を非表示にします。"}
    rng = np.random.default_rng(seed % (2**32))
    samples = rng.choice(values, size=(2000, n), replace=True).mean(axis=1)
    return {"ci95": [float(x) for x in np.quantile(samples, [.025,.975])],
            "status": "reference" if n < 20 else "available", "independent_deals": n,
            "reason": "配札平均を単位とする百分位ブートストラップ。独立配札・代表性を仮定。" +
                      ("20件未満の参考区間です。" if n < 20 else "多重比較や選択の偏りは補正していません。")}


def complete_deals(config, rows, setting):
    from .rollout_quality import Setting
    grouped = defaultdict(list)
    for row in rows:
        if row.get("setting") == setting.identifier:
            grouped[row.get("deal_id")].append(row)
    complete = {}
    for deal, group in grouped.items():
        if len(group) != 6 or {r.get("rotation") for r in group} != set(range(6)):
            continue
        try:
            for row in group:
                seed, rotation = row["seed"], row["rotation"]
                roles = ROTATIONS[rotation]
                names = tuple(setting.strategy_name if role == 0 else config.opponents[role-1] for role in roles)
                if (type(seed) is not int or seed not in config.deal_seeds or deal != str(seed)
                        or type(rotation) is not int or tuple(row["roles"]) != roles
                        or type(row["seat"]) is not int or row["seat"] != roles.index(0)
                        or tuple(row["strategies"]) != names
                        or type(setting).model_validate(row["rollout_parameters"]).model_dump() != setting.model_dump()
                        or row["strategy_version"] != getattr(setting,'strategy_version','1')
                        or any(type(v) is not int for v in row["terminal_rewards"])
                        or tuple(row["terminal_rewards"]) != terminal_rewards(row["winners"])):
                    raise ValueError("比較条件不一致")
            complete[deal] = sorted(group, key=lambda r:r["rotation"])
        except (KeyError, ValueError, TypeError, IndexError):
            continue
    return complete


def paired_clusters(first, second, first_setting, second_setting, seed):
    if (first_setting.budget_family != second_setting.budget_family
            or first_setting.total_budget != second_setting.total_budget
            or first_setting.min_trials != second_setting.min_trials
            or (first_setting.budget_family=='budget' and first_setting.continuation!=second_setting.continuation)):
        return {"comparable":False,"reasons":["総予算・最低試行・予算方式・継続条件が一致しません。"],
                "difference":None,"ci95":None,"independent_deals":0,"matched_deals":[]}
    if first_setting.time_limit_ms != second_setting.time_limit_ms:
        return {"comparable": False, "reasons": ["判断時間上限が異なります。"], "difference": None,
                "ci95": None, "independent_deals": 0, "matched_deals": []}
    samples = paired_deal_differences(first, second)
    matched, differences = list(samples), list(samples.values())
    info = uncertainty(differences,seed)
    return {"comparable": bool(matched), "reasons": [] if matched else ["条件が一致する完全な共通配札がありません。"],
            "difference": float(np.mean(differences)) if differences else None, "ci95": info["ci95"],
            "independent_deals": len(matched), "matched_deals": matched, "uncertainty": info,
            "first_only_deals": sorted(first.keys()-set(matched)), "second_only_deals": sorted(second.keys()-set(matched))}


def paired_deal_differences(first, second):
    """比較条件検証済みの配札群から、役割対応を再確認してB−Aを返す。"""
    samples = {}
    for deal in sorted(first.keys() & second.keys()):
        a,b = first[deal],second[deal]
        keys = lambda rows: [(r['seed'],r['rotation'],tuple(r['roles']),r['seat'],
                              tuple('target' if p==r['seat'] else n for p,n in enumerate(r['strategies']))) for r in rows]
        if keys(a) == keys(b):
            samples[deal] = float(np.mean([y['terminal_rewards'][y['seat']]-x['terminal_rewards'][x['seat']] for x,y in zip(a,b)]))
    return samples


def decision_sources(payload):
    hashes=payload.get("runtime",{}).get("source_sha256",{})
    return {k:v for k,v in hashes.items() if k.startswith(("game/","strategies/")) or k in ("rollouts.py","inference.py","experiments/runner.py","experiments/rollout_quality.py","experiments/arena.py")}


def compare_saved(first, second, first_name, second_name):
    # 外部ファイルの合算ではなく、保存済みの条件が揃った部分だけを比較する。
    from .rollout_quality import StudyConfig
    a = StudyConfig.model_validate(first["config"])
    b = StudyConfig.model_validate(second["config"])
    left = next((s for s in a.settings if s.identifier==first_name),None)
    right = next((s for s in b.settings if s.identifier==second_name),None)
    if left is None or right is None:
        raise ValueError("指定設定が保存結果にありません")
    reasons = []
    for name,x,y in [("対戦相手",a.opponents,b.opponents),("方策seed",a.policy_seed,b.policy_seed),
                     ("基準コミット",a.baseline_commit,b.baseline_commit),
                     ("seed用途区分",a.seed_partition,b.seed_partition),
                     ("ルール",first.get("rule_version"),second.get("rule_version")),
                     ("報酬版",first.get("reward_version"),second.get("reward_version")),
                     ("情報条件",first.get("information_condition","imperfect"),second.get("information_condition","imperfect")),
                     ("役割別seed方式",first.get("runner_seed_scheme","quality-policy-v1"),second.get("runner_seed_scheme","quality-policy-v1"))]:
        if x != y or x is None: reasons.append(name+"が一致しません。")
    sources_a,sources_b=decision_sources(first),decision_sources(second)
    required={"game/engine.py","game/rules.py","strategies/monte_carlo.py","strategies/baselines.py","rollouts.py","inference.py","experiments/runner.py","experiments/rollout_quality.py"}
    if left.budget_family=='budget' or right.budget_family=='budget':
        required.update(("strategies/hybrid.py","strategies/registry.py"))
    if left.method.startswith('theory') or right.method.startswith('theory'):
        required.update(('strategies/theories.py','strategies/theory_policy.py','strategies/registry.py'))
    if not required <= sources_a.keys() or not required <= sources_b.keys() or sources_a != sources_b:
        reasons.append("対局・戦略ソースのfingerprintが一致しないか未記録です。")
    context = {"first_opponents": a.opponents, "second_opponents": b.opponents,
               "first_deals":a.deal_seeds,"second_deals":b.deal_seeds,
               "first_policy_seed":a.policy_seed,"second_policy_seed":b.policy_seed,
               "first_parameters":left.model_dump(),"second_parameters":right.model_dump()}
    if reasons:
        return {"comparable":False,"reasons":reasons,"difference":None,"ci95":None,"independent_deals":0,"conditions":context}
    return {**paired_clusters(complete_deals(a,first["results"],left),complete_deals(b,second["results"],right),left,right,a.policy_seed),
            "conditions":context,"direction":"second − first"}
