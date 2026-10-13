"""宣言定義を固定してリーグを再実行する。既定は見積もりのみ。"""
import argparse
import json
from pathlib import Path
from time import sleep
from .arena import ArenaRequest,arena_estimate,arena_jobs
from .storage import ExperimentStore
from ..strategies.declarative import DefinitionStore,builtin_definitions


def main():
    parser=argparse.ArgumentParser(description='Codex Strategy Arena。実行には--runが必要です。')
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--database',type=Path,default=Path('research-local/arena.sqlite'))
    parser.add_argument('--output',type=Path)
    parser.add_argument('--run',action='store_true')
    args=parser.parse_args()
    class InitialDefinitions:
        def get(self,reference):
            value=next((d for d in builtin_definitions() if d.reference==reference),None)
            if value is None:raise ValueError('初期定義にありません。登録済みDBを指定してください')
            return value
    definitions=DefinitionStore(args.database) if args.database.exists() else InitialDefinitions()
    request=ArenaRequest.model_validate_json(args.config.read_text(encoding='utf-8'))
    plan=request.resolve(definitions)
    print(json.dumps(arena_estimate(plan),ensure_ascii=False),flush=True)
    if not args.run:return
    args.database.parent.mkdir(parents=True,exist_ok=True)
    DefinitionStore(args.database)
    jobs=arena_jobs(ExperimentStore(args.database));identifier=jobs.submit(plan)['id'];previous=-1
    try:
        while True:
            result=jobs.get(identifier)
            if result['completed_games']!=previous:
                previous=result['completed_games'];print(f"{identifier}: {previous}/{result['estimate']['games']} {result['status']}",flush=True)
            if result['status'] not in ('running','cancelling'):break
            sleep(.3)
    except KeyboardInterrupt:
        jobs.cancel(identifier)
        while jobs.get(identifier)['status'] in ('running','cancelling'):sleep(.1)
    finally:jobs.close()
    result=jobs.get(identifier,True)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'id':identifier,'status':result['status'],'summary':result['summary']},ensure_ascii=False))
    if result['status']!='completed':raise SystemExit(1)


if __name__=='__main__':main()
