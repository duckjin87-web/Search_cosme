"""작업 실행. SC_QUEUE=celery 면 Redis 큐 → 별도 워커, inline 이면 API 프로세스의 스레드."""
from __future__ import annotations

import threading

from celery import Celery

from searchcosme.config import settings

celery_app = Celery("searchcosme", broker=settings.redis_url)
celery_app.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_default_queue="lookups")


@celery_app.task(name="searchcosme.run_lookup")
def run_lookup_task(lookup_id: str) -> int | None:
    from searchcosme.pipeline import run_lookup
    return run_lookup(lookup_id)


def dispatch(lookup_id: str) -> None:
    if settings.queue == "celery":
        run_lookup_task.delay(lookup_id)
    else:
        from searchcosme.pipeline import run_lookup
        threading.Thread(target=run_lookup, args=(lookup_id,), daemon=True).start()
