"""Evaluation Labの固定計画JSON。既定は見積もりだけ。"""
import argparse
import json
from pathlib import Path
from time import sleep
from .evaluation_lab import EvaluationRequest,EvaluationJobs,ablation_definitions,estimate_evaluation
from .arena import arena_jobs
from .evolution import Evolution
from .storage import ExperimentStore
from ..strategies.declarative import DefinitionStore,builtin_definitions


def main():
    parser=argparse.ArgumentParser(description='Evaluation Lab。対戦は--run指定時だけ')
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--database',type=Path,default=Path('research-local/evaluation.sqlite'))
    parser.add_argument('--output',type=Path)
    parser.add_argument('--run',action='store_true')
    args=parser.parse_args();request=EvaluationRequest.model_validate_json(args.config.read_text(encoding='utf-8'))
    values=ablation_definitions(request.purpose) if request.purpose!='comparison' else builtin_definitions()
    class Preview:
        def get(self,reference):
            value=next((d for d in [*builtin_definitions(),*values] if d.reference==reference),None)
            if value is None:raise ValueError('CLIプレビューにない登録版です。UI/APIで指定してください')
            return value
    print(json.dumps(estimate_evaluation(request,Preview()),ensure_ascii=False),flush=True)
    if not args.run:return
    args.database.parent.mkdir(parents=True,exist_ok=True);definitions=DefinitionStore(args.database)
    for d in values:definitions.add(d)
    store=ExperimentStore(args.database);arena=arena_jobs(store);jobs=EvaluationJobs(store,definitions,arena,Evolution(store,definitions,arena))
    identifier=jobs.submit(request)['id'];previous=-1
    try:
        while True:
            result=jobs.get(identifier)
            if result['completed_games']!=previous:
                previous=result['completed_games'];print(identifier,previous,result['status'],flush=True)
            if result['status']!='running':break
            sleep(.2)
    except KeyboardInterrupt:
        jobs.cancel(identifier)
        while jobs.get(identifier)['status']=='running':sleep(.1)
    finally:jobs.close();arena.close()
    result=jobs.get(identifier)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'id':identifier,'status':result['status'],'elapsed_seconds':result['elapsed_seconds']},ensure_ascii=False))
    if result['status']!='completed':raise SystemExit(1)


if __name__=='__main__':main()
