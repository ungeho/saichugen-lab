"""層別Planの明示登録・実行・保存。通常は見積もりだけ。"""
import argparse,json
from pathlib import Path
from time import sleep
from .storage import ExperimentStore
from .arena import arena_jobs
from .evolution import Evolution
from .evaluation_lab import EvaluationJobs
from .design_lab import DesignLab
from .evidence_lab import EvidenceLab
from .stratification_lab import StratificationJobs,StratificationConfig,stratification_estimate
from ..strategies.declarative import DefinitionStore

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True,type=Path);p.add_argument('--database',type=Path,default=Path('research-local/stratification.sqlite'));p.add_argument('--register',action='store_true');p.add_argument('--run');p.add_argument('--output',type=Path);a=p.parse_args()
    c=StratificationConfig.model_validate_json(a.config.read_text(encoding='utf-8-sig'));print(json.dumps(stratification_estimate(c)),flush=True)
    if not a.register and not a.run:return
    a.database.parent.mkdir(parents=True,exist_ok=True);s=ExperimentStore(a.database);defs=DefinitionStore(s.path);arena=arena_jobs(s);evo=Evolution(s,defs,arena);ev=EvaluationJobs(s,defs,arena,evo);design=DesignLab(s,defs,ev,evo);lab=StratificationJobs(s,design,EvidenceLab(s,design))
    try:
        v=lab.register(c) if a.register else lab.get(a.run)
        if v['config']!=c.model_dump(mode='json'):raise ValueError('登録とファイルの条件が不一致')
        if a.run:
            v=lab.start(a.run,v['condition_hash'])
            while v['status']=='Running':sleep(.3);v=lab.get(a.run);print(v['status'],v['progress'],flush=True)
        if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'id':v['id'],'status':v['status'],'hash':v['condition_hash'],'positions':len(v['positions']),'seconds':v['elapsed_seconds']}),flush=True)
        if a.run and v['status']!='Completed':raise SystemExit(1)
    except KeyboardInterrupt:
        lab.cancel(a.run)
        while lab.get(a.run)['status']=='Running':sleep(.1)
    finally:lab.close();design.close();ev.close();arena.close()

if __name__=='__main__':main()
