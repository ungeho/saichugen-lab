"""単一ローカルワーカー。完了した対局だけを既存SQLiteへ保存する。"""
from threading import Event, Lock, Thread
from time import monotonic

from .rollout_quality import KIND, StudyConfig, estimate, runtime_info, run_study, probe, summarize_study
from ..game.rules import RULE_VERSION
from ..game.rewards import REWARD_VERSION
from ..strategies.theories import theory_catalog


class StudyStopped(Exception):
    def __init__(self, status):
        self.status = status


class QualityJobs:
    def __init__(self, store, *, kind=KIND, config_model=None, runner=None, prober=None, summarizer=None, planner=None, seed_scheme='quality-policy-v1'):
        self.store = store
        self.kind,self.config_model=kind,config_model or StudyConfig
        self.runner,self.prober,self.summarizer,self.planner=runner,prober,summarizer,planner
        self.seed_scheme=seed_scheme
        self.lock = Lock()
        self.active = None
        self.cancel_event = None
        self.owned = set()
        self.closed = False

    def submit(self, config):
        with self.lock:
            if self.closed or self.active is not None:
                raise RuntimeError("探索品質実験は1件ずつ実行してください")
            payload = {"experiment_kind": self.kind, "schema_version": 1, "status": "running",
                       "baseline_commit": config.baseline_commit, "config": config.model_dump(mode='json'),
                       "rule_version": RULE_VERSION, "reward_version": REWARD_VERSION,
                       "runtime": runtime_info(), "estimate": (self.planner or estimate)(config,[p for i,p in self.store.iter_experiments()]), "results": [], "positions": [], "partial_games": [],
                       "information_condition":"imperfect", "runner_seed_scheme":self.seed_scheme,
                       "statistics_version":"deal-cluster-v2",
                       "strategy_manifest":[{'setting':s.identifier,'strategy_id':s.strategy_name,'strategy_version':getattr(s,'strategy_version','1'),
                           'parameters':s.model_dump(mode='json'),'theories':s.theory_config.model_dump() if s.theory_config else None,
                           'parent_strategy':'HybridSearch' if s.method.startswith('theory_search') else None,
                           'hypothesis_status':'未検証' if s.method.startswith('theory') else '比較対象'} for s in config.settings],
                       "theory_manifest":[d for d in theory_catalog() if any(s.theory_config and any(t.id==d['id'] for t in s.theory_config.theories) for s in config.settings)],
                       "elapsed_seconds": 0, "error": None}
            identifier = self.store.save(payload)
            self.active = identifier
            self.owned.add(identifier)
            cancelled = self.cancel_event = Event()
        def worker():
            started = monotonic()
            def check():
                if cancelled.is_set():
                    raise StudyStopped("cancelled")
                if monotonic()-started >= config.timeout_seconds:
                    raise StudyStopped("timed_out")
            def persist():
                payload["elapsed_seconds"] = monotonic()-started
                self.store.update(identifier, payload)
            def on_row(row):
                payload["results"].append(row)
                persist()
            def on_partial(row):
                payload["partial_games"].append(row)
                persist()
            try:
                if config.analyze_position:
                    payload["positions"].append((self.prober or probe)(config, check))
                    persist()
                (self.runner or run_study)(config, on_row, check, on_partial)
                check()
                payload["status"] = "completed"
            except StudyStopped as error:
                payload["status"] = error.status
            except Exception as error:
                payload["status"] = "failed"
                payload["error"] = f"実験に失敗しました ({type(error).__name__})"
            finally:
                try:
                    persist()
                finally:
                    with self.lock:
                        self.active = None
                        self.cancel_event = None
        Thread(target=worker, daemon=True, name="rollout-quality").start()
        return self.get(identifier)

    def get(self, identifier, full=False):
        payload = self.store.get(identifier)
        if payload is None or payload.get("experiment_kind") != self.kind:
            raise KeyError(identifier)
        with self.lock:
            if payload["status"] in ("running", "cancelling") and identifier not in self.owned:
                payload["status"] = "interrupted"
            cancelling = identifier == self.active and self.cancel_event.is_set()
        if cancelling:
            payload["status"] = "cancelling"
        config = self.config_model.model_validate(payload["config"])
        result = {"id": identifier, **payload, "completed_games": len(payload["results"]),
                  "summary": (self.summarizer or summarize_study)(config, payload["results"], payload.get("partial_games", []))}
        if not full:
            result.pop("results")
            result.pop("partial_games", None)
        return result

    def cancel(self, identifier):
        self.get(identifier)
        with self.lock:
            if self.active == identifier:
                self.cancel_event.set()
        return self.get(identifier)

    def history(self):
        return [{"id": i, "name": p["config"]["name"], "status": self.get(i)["status"],
                 "completed_games": len(p["results"])}
                for i,p in self.store.iter_experiments() if p.get("experiment_kind") == self.kind]

    def close(self):
        with self.lock:
            self.closed = True
            if self.cancel_event is not None:
                self.cancel_event.set()
