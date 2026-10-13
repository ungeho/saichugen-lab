"""事前記録した親子提案を同条件で再実行。既定は見積もりのみ。"""
import argparse
import json
from pathlib import Path
from time import sleep
from .evolution import Evolution, EvolutionRequest, StageRequest
from .storage import ExperimentStore
from .arena import arena_jobs, ArenaRequest, arena_estimate
from ..strategies.declarative import StrategyDefinition, DefinitionStore, builtin_definitions


def main():
    parser=argparse.ArgumentParser(description='Strategy Evolution：--runなしでは見積もりだけ')
    parser.add_argument('--proposal',type=Path,required=True)
    parser.add_argument('--database',type=Path,default=Path('research-local/evolution.sqlite'))
    parser.add_argument('--output',type=Path)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--validation',action='store_true',help='事前固定した子を検証配札でも評価。最終評価は実行しない')
    args=parser.parse_args()
    data=json.loads(args.proposal.read_text(encoding='utf-8'))
    if set(data)!={'definition','experiment'}:raise ValueError('提案はdefinitionとexperimentだけを指定してください')
    child=StrategyDefinition.model_validate(data['definition']);request=EvolutionRequest.model_validate(data['experiment'])
    if request.children!=[child.reference]:raise ValueError('提案と評価候補が一致しません')
    class Preview:
        def get(self,ref):
            if ref==child.reference:return child
            return next(d for d in builtin_definitions() if d.reference==ref)
    for stage in ('development','validation'):
        plan=ArenaRequest(participants=[request.parent,*request.children],opponents=request.opponents,deals=request.deals,
            seed_partition=stage,start_offset=getattr(request,stage+'_offset'),policy_seed=request.policy_seed,
            include_expensive=request.include_expensive,timeout_seconds=request.timeout_seconds).resolve(Preview())
        print(stage,json.dumps(arena_estimate(plan),ensure_ascii=False),flush=True)
    if not args.run:return
    args.database.parent.mkdir(parents=True,exist_ok=True)
    definitions=DefinitionStore(args.database);definitions.add(child);store=ExperimentStore(args.database);jobs=arena_jobs(store);service=Evolution(store,definitions,jobs)
    view=service.create(request);identifier=view['id']
    try:
        for stage in ('development','validation') if args.validation else ('development',):
            view=service.start(identifier,stage,StageRequest(children=request.children))
            previous=-1
            while True:
                view=service.get(identifier);result=view['stages'][stage]['result']
                if previous!=result['completed_games']:
                    previous=result['completed_games'];print(stage,previous,result['status'],flush=True)
                if result['status'] not in ('running','cancelling'):break
                sleep(.2)
            if result['status']!='completed':break
    except KeyboardInterrupt:
        for stage in view['stages'].values():
            if stage['result']['status'] in ('running','cancelling'):jobs.cancel(stage['arena_id'])
        while any(s['result']['status'] in ('running','cancelling') for s in service.get(identifier)['stages'].values()):sleep(.1)
    finally:jobs.close()
    view=service.get(identifier)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(view,ensure_ascii=False,indent=2),encoding='utf-8')
    print(identifier,json.dumps(view['candidates'],ensure_ascii=False),flush=True)
    if any(s['result']['status']!='completed' for s in view['stages'].values()):raise SystemExit(1)


if __name__=='__main__':main()
