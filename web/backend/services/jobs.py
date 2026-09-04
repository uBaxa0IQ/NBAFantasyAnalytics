"""Bounded, deduplicated background jobs for expensive draft benchmarks."""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import monotonic
from uuid import uuid4

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='benchmark')
_jobs = {}
_lock = Lock()


def submit(key, operation):
    with _lock:
        now = monotonic()
        for job_id, job in list(_jobs.items()):
            if job['future'].done() and now - job['created'] > 1800:
                del _jobs[job_id]
        for job_id, job in _jobs.items():
            if job['key'] == key and not (job['future'].done() and job['future'].exception()):
                return job_id
        if len(_jobs) >= 20 or sum(not job['future'].done() for job in _jobs.values()) >= 2:
            raise ValueError('Очередь расчётов занята. Повторите позже.')
        job_id = uuid4().hex
        _jobs[job_id] = {'key': key, 'created': now, 'future': _executor.submit(operation)}
        return job_id


def status(job_id):
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        return None
    future = job['future']
    if not future.done():
        return {'status': 'running' if future.running() else 'queued'}
    if future.exception():
        return {'status': 'failed', 'error': 'Расчёт не завершён. Проверьте подключение ESPN и повторите.'}
    return {'status': 'complete', 'result': future.result()}
