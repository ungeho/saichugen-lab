"""Plan JSONを別操作で草案化・登録・実行する。既定は見積もりだけ。"""
import argparse
import json
from pathlib import Path
from time import sleep
from .design_lab import DesignLab,PlanSpec
from .evaluation_lab import EvaluationJobs,ablation_definitions
from .arena import arena_jobs
from .evolution import Evolution
from .storage import ExperimentStore
from ..strategies.declarative import DefinitionStore


def main():
    parser=argparse.ArgumentParser(description='Experimental Design Lab。登録と実行を明示的に分離。')
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--database',type=Path,default=Path('research-local/design.sqlite'))
    parser.add_argument('--output',type=Path)
    parser.add_argument('--register',action='store_true')
    parser.add_argument('--run',action='store_true')
    args=parser.parse_args();spec=PlanSpec.model_validate_json(args.plan.read_text(encoding='utf-8'))
    args.database.parent.mkdir(parents=True,exist_ok=True);definitions=DefinitionStore(args.database)
    for d in ablation_definitions('adaptive_ablation'):definitions.add(d)
    store=ExperimentStore(args.database);arena=arena_jobs(store);evolution=Evolution(store,definitions,arena);evaluation=EvaluationJobs(store,definitions,arena,evolution);lab=DesignLab(store,definitions,evaluation,evolution)
    print(json.dumps(lab.estimate(spec),ensure_ascii=False),flush=True)
    if not args.register and not args.run:
        lab.close();evaluation.close();arena.close();return
    try:
        try:view=lab.get(spec.plan_id,spec.version)
        except KeyError:
            if not args.register:raise ValueError('先に--registerでPlanを登録してください') from None
            view=lab.draft(spec)
        if view['spec']!=spec.model_dump(mode='json'):raise ValueError('ファイルと保存済みPlanが一致しません。別版を作ってください')
        if args.register and view['state']=='Draft':view=lab.register(spec.plan_id,spec.version)
        if args.run:
            if view['state']!='Registered':raise ValueError('実行にはRegisteredのPlanが必要です')
            view=lab.start(spec.plan_id,spec.version,view['plan_hash']);previous=-1
            while view['state']=='Running':
                count=(view.get('usage') or {}).get('completed_games',0)
                if count!=previous:print(view['state'],count,flush=True);previous=count
                sleep(.2);view=lab.get(spec.plan_id,spec.version)
    except KeyboardInterrupt:
        lab.cancel(spec.plan_id,spec.version)
        while lab.get(spec.plan_id,spec.version)['state']=='Running':sleep(.1)
    finally:lab.close();evaluation.close();arena.close()
    view=lab.get(spec.plan_id,spec.version)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(view,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'id':view['id'],'version':view['version'],'state':view['state'],'plan_hash':view['plan_hash'],'usage':view.get('usage')},ensure_ascii=False),flush=True)
    if args.run and view['state']!='Completed':raise SystemExit(1)


if __name__=='__main__':main()
