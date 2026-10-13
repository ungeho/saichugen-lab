"""JSONプリセットを見積もり、明示的な--runで実行する。"""
import argparse
import json
from pathlib import Path
from time import sleep

from .rollout_quality import StudyConfig, estimate
from .quality_jobs import QualityJobs
from .storage import ExperimentStore


def main():
    parser = argparse.ArgumentParser(description="Rollout探索品質評価。既定は見積もりだけ。")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=Path("research-local/quality-studies.sqlite"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    config = StudyConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
    history=list(ExperimentStore(args.database).iter_experiments()) if args.database.exists() else []
    print(json.dumps(estimate(config,[p for i,p in history]), ensure_ascii=False))
    if not args.run:
        print("実行する場合だけ--runを追加してください。")
        return
    args.database.parent.mkdir(parents=True, exist_ok=True)
    jobs = QualityJobs(ExperimentStore(args.database))
    identifier = jobs.submit(config)["id"]
    previous = -1
    try:
        while True:
            result = jobs.get(identifier)
            if result["completed_games"] != previous:
                previous = result["completed_games"]
                print(f"{identifier}: {previous}/{result['estimate']['games']} 対局 {result['status']}", flush=True)
            if result["status"] not in ("running", "cancelling"):
                break
            sleep(.3)
    except KeyboardInterrupt:
        jobs.cancel(identifier)
        while jobs.get(identifier)["status"] in ("running", "cancelling"):
            sleep(.3)
    finally:
        jobs.close()
    result = jobs.get(identifier, full=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"id": identifier, "status": result["status"], "summary": result["summary"]}, ensure_ascii=False))
    if result["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
