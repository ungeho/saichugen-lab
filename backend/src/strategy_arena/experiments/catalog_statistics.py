"""既存の保存結果を条件ごとに分けて、図鑑向けに集計する。"""

from collections import Counter
import json


def algorithm_statistics(name: str, experiments) -> dict:
    groups = {}
    unclassified = 0
    for identifier, payload in experiments:
        try:
            rule = payload["rule_version"]
            condition = payload["information_condition"]
            versions = payload["strategy_versions"]
            if not rule or not condition:
                raise ValueError("条件不足")
            parameters = payload.get("strategy_parameters")
            # 既存結果の未記録設定を、新しい結果の既定設定と同一視しない。
            settings = json.dumps(parameters, sort_keys=True, ensure_ascii=False)
            rows = payload["results"]
            for row in rows:
                names = row["strategies"]
                if len(names) != 3 or len(row["scores"]) != 3 or any(p not in (0, 1, 2) for p in row["winners"]):
                    raise ValueError("結果形式不正")
                if any(n not in versions or not versions[n] for n in names):
                    raise ValueError("バージョン不足")
        except (KeyError, TypeError, ValueError):
            unclassified += 1
            continue
        for index, row in enumerate(rows):
            for p, participant in enumerate(row["strategies"]):
                if participant != name:
                    continue
                opponents = sorted((n, str(versions[n])) for q, n in enumerate(row["strategies"]) if q != p)
                key = (rule, condition, str(versions[name]), tuple(opponents), settings)
                if key not in groups:
                    groups[key] = {"rule_version": rule, "information_condition": condition,
                                   "strategy_version": str(versions[name]), "parameters": parameters,
                                   "opponents": [{"name": n, "version": v} for n, v in opponents],
                                   "scores": [], "wins": 0, "matches": set(), "experiment_ids": set()}
                group = groups[key]
                group["scores"].append(row["scores"][p])
                group["wins"] += int(p in row["winners"])
                group["matches"].add((identifier, index))
                group["experiment_ids"].add(identifier)
    output = []
    for group in groups.values():
        scores = group["scores"]
        counts = Counter(scores)
        output.append({**{k: v for k, v in group.items() if k not in ("scores", "matches", "experiment_ids")},
                       "participations": len(scores), "match_count": len(group["matches"]),
                       "experiment_ids": sorted(group["experiment_ids"]),
                       "win_rate": group["wins"] / len(scores), "average_score": sum(scores) / len(scores),
                       "score_distribution": [{"score": score, "count": count} for score, count in sorted(counts.items())]})
    return {"name": name, "groups": output, "unclassified_experiments": unclassified,
            "note": "ルール・情報条件・全員のバージョン・相手構成・記録済み設定ごとに集計。再実行して保存した試合も含みます。共同勝利は各人1勝です。"}
