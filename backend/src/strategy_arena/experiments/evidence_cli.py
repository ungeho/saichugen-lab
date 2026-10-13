"""Evidence CLI。実験実行はdesign_cliへ分離する。"""
import argparse,json
from pathlib import Path
from .storage import ExperimentStore
from .arena import arena_jobs
from .evolution import Evolution
from .evaluation_lab import EvaluationJobs
from .design_lab import DesignLab
from .evidence_lab import EvidenceLab,SeriesSpec,EvidenceSource,Projection
from ..strategies.declarative import DefinitionStore

def main():
    p=argparse.ArgumentParser(description='Evidence Seriesの作成・関連付け・出力（対局は実行しない）')
    p.add_argument('--database',type=Path,default=Path('research-local/design.sqlite'))
    p.add_argument('--create',type=Path);p.add_argument('--series',required=True);p.add_argument('--version',type=int,default=1)
    p.add_argument('--source',type=Path);p.add_argument('--additional-deals',type=int);p.add_argument('--output',type=Path)
    a=p.parse_args();a.database.parent.mkdir(parents=True,exist_ok=True)
    store=ExperimentStore(a.database);defs=DefinitionStore(a.database);arena=arena_jobs(store);evo=Evolution(store,defs,arena);jobs=EvaluationJobs(store,defs,arena,evo);design=DesignLab(store,defs,jobs,evo);lab=EvidenceLab(store,design)
    try:
        if a.create:
            spec=SeriesSpec.model_validate_json(a.create.read_text(encoding='utf-8-sig'))
            if (spec.series_id,spec.version)!=(a.series,a.version):raise ValueError('CLIとSeries識別子が不一致')
            lab.create(spec)
        if a.source:lab.add(a.series,a.version,EvidenceSource.model_validate_json(a.source.read_text(encoding='utf-8-sig')))
        result=lab.get(a.series,a.version)
        if a.additional_deals:result['projection']=lab.project(a.series,a.version,Projection(additional_deals=a.additional_deals))
        text=json.dumps(result,ensure_ascii=False,indent=2)
        if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(text,encoding='utf-8')
        else:print(text)
    finally:design.close();jobs.close();arena.close()

if __name__=='__main__':main()
