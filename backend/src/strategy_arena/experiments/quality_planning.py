"""実測履歴を優先する時間・JSON保存量の概算。実行保証ではない。"""
import json
import os
import platform
from hashlib import sha256
from pathlib import Path
from .quality_statistics import decision_sources
from ..game.rules import RULE_VERSION
from ..game.rewards import REWARD_VERSION
from statistics import mean, median

REFERENCE_SECONDS_8 = {"Random": .4, "Greedy": 7.8, "ScoreAware": 7.84}


def resource_plan(config, historical=()):
    seconds = 0.0
    sources = []
    sizes = []
    known = True
    cpu = os.environ.get("PROCESSOR_IDENTIFIER", platform.processor())
    source_root=Path(__file__).resolve().parents[1]
    current={p.relative_to(source_root).as_posix():sha256(p.read_bytes()).hexdigest() for p in source_root.rglob('*.py')} if historical else {}
    current=decision_sources({'runtime':{'source_sha256':current}})
    for setting in config.settings:
        times = []
        for payload in historical:
            if (payload.get("experiment_kind") != "rollout_quality_v1"
                    or tuple(payload.get("config",{}).get("opponents",())) != config.opponents
                    or payload.get("runtime",{}).get("cpu") != cpu
                    or payload.get("rule_version") != RULE_VERSION or payload.get("reward_version") != REWARD_VERSION
                    or decision_sources(payload) != current):
                continue
            for row in payload.get("results",[]):
                from .rollout_quality import Setting
                if Setting.model_validate(row.get("rollout_parameters",{})).model_dump() == setting.model_dump() and row.get("game_elapsed_ns",0)>0:
                    times.append(row["game_elapsed_ns"]/1e9)
                    sizes.append(len(json.dumps(row,ensure_ascii=False).encode("utf-8")))
        if times:
            per_game = mean(times)
            sources.append({"setting":setting.identifier,"source":"同CPU・同相手・同設定・同実装の完了対局", "samples":len(times),"game_seconds":per_game})
        elif setting.budget_family=='direct':
            per_game=.05
            sources.append({'setting':setting.identifier,'source':'直接評価の未校正参考値。先に少数配札で測定してください','samples':0,'game_seconds':per_game})
        elif setting.continuation in REFERENCE_SECONDS_8 and setting.time_limit_ms is None:
            per_game = REFERENCE_SECONDS_8[setting.continuation]*(setting.trials/8 if setting.method=="legacy" else setting.total_budget*15/1200)
            sources.append({"setting":setting.identifier,"source":"Phase17参考値のRollout数比例モデル。Hybridの追加処理・再サンプル費用は未校正", "samples":0,"game_seconds":per_game})
        else:
            per_game = 0
            known = False
            sources.append({"setting":setting.identifier,"source":"未校正。小規模測定が必要", "samples":0,"game_seconds":None})
        seconds += per_game*6*len(config.deal_seeds)
    seconds += 2 if config.analyze_position else 0
    row_size = int(median(sizes)) if sizes else 4096
    storage = row_size*6*len(config.deal_seeds)*len(config.settings)+65536
    return {"estimated_seconds":seconds if known else None,
            "estimated_seconds_range":[seconds*.5,seconds*2] if known else None,
            "estimated_storage_bytes":storage,"timing_sources":sources,
            "resource_note":"時間は0.5〜2倍を目安とする概算で上限保証ではありません。保存量はJSONのみ、SQLiteページ・ログ・履歴領域は別。"}
