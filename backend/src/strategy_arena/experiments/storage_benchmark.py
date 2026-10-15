"""既存DBを読み書きしない、合成データ専用の保存負荷測定。"""
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from threading import Lock

_lock = Lock()
from .storage import ExperimentStore


def run_storage_benchmark(root, environment, *, timeout_seconds=20):
    if not _lock.acquire(blocking=False):
        raise RuntimeError('保存負荷測定は同時に1件のみ')
    try:
        return _run(root, environment, timeout_seconds=timeout_seconds)
    finally:
        _lock.release()


def _run(root, environment, *, timeout_seconds):
    if not 1 <= timeout_seconds <= 30:
        raise ValueError('保存測定の上限は1〜30秒')
    identifier = str(uuid4())
    directory = Path(root) / identifier
    directory.mkdir(parents=True, exist_ok=False)
    start = perf_counter()
    cases = []
    status = 'Completed'
    for history in (0, 50, 250):
        for size in (16384, 2097152):
            for saves in (1, 4, 12):
                if perf_counter() - start >= timeout_seconds:
                    status = 'TimedOut'
                    break
                setup = perf_counter()
                store = ExperimentStore(directory / f'{history}-{size}-{saves}.sqlite')
                for _ in range(history):
                    store.save({'synthetic': True, 'text': 'x' * 256})
                payload = {'synthetic': True, 'text': 'x' * size}
                row = store.save({'synthetic': True})
                setup_seconds = perf_counter() - setup
                writes = []
                metrics = []
                for _ in range(saves):
                    tick = perf_counter()
                    store.update(row, payload, on_write=metrics.append)
                    writes.append(perf_counter() - tick)
                tick = perf_counter()
                assert store.get(row) == payload
                read_seconds = perf_counter() - tick
                tick = perf_counter()
                count = sum(1 for _ in store.iter_experiments())
                aggregate_seconds = perf_counter() - tick
                measured = sum(writes) + read_seconds + aggregate_seconds
                cases.append({'history_rows': history, 'save_count': saves,
                    'frequency': f'12管理イベントあたり{saves}回（合成条件）',
                    'payload_bytes': metrics[0]['written_bytes'],
                    'written_bytes': sum(m['written_bytes'] for m in metrics),
                    'transactions': sum(m['transactions'] for m in metrics),
                    'write_seconds': writes, 'read_seconds': read_seconds,
                    'aggregate_seconds': aggregate_seconds, 'rows_read': count,
                    'setup_seconds': setup_seconds, 'measured_seconds': measured,
                    'save_share': sum(writes) / measured})
            if status != 'Completed': break
        if status != 'Completed': break
    return {'id': identifier, 'kind': 'calibration_storage_benchmark_v1',
        'status': status, 'environment': environment, 'cases': cases,
        'elapsed_seconds': perf_counter() - start,
        'scope': '新規の合成DBのみ。バイト数はJSONの論理量、物理I/O量ではない。設定順の記述測定で因果推論ではない。'}
