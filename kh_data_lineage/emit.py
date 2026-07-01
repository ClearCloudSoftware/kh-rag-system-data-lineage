# kh_data_lineage/emit.py
import atexit
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from openlineage.client import OpenLineageClient
from openlineage.client.transport.http import HttpConfig, HttpTransport

log = logging.getLogger("kh_data_lineage")

# ponytail: one process-wide pool + one atexit flush, shared by every AsyncEmitter,
# so building many trackers/void_runs can't leak threads or atexit callbacks.
# max_workers applies only to the first emitter that creates the pool. Created lazily
# from the constructing (main) thread; add a lock if emitters are ever built off-thread.
_pool: ThreadPoolExecutor | None = None


def _get_pool(max_workers: int) -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=max_workers)
        atexit.register(_pool.shutdown, wait=True)
    return _pool


def _build_client(marquez_url: str) -> OpenLineageClient:
    return OpenLineageClient(transport=HttpTransport(HttpConfig(url=marquez_url)))


class AsyncEmitter:
    def __init__(self, client, *, max_workers: int = 4, retries: int = 3):
        self._client, self._retries = client, retries
        self._pool = _get_pool(max_workers)

    def emit(self, run_event) -> None:
        try:
            self._pool.submit(self._emit_with_retry, run_event)
        except RuntimeError:  # pool already shut down at interpreter exit
            log.warning("lineage emit skipped: pool already shut down")

    def _emit_with_retry(self, run_event) -> None:
        for attempt in range(1, self._retries + 1):
            try:
                self._client.emit(run_event)
                return
            except Exception as exc:
                log.warning("lineage emit failed (%d/%d): %s", attempt, self._retries, exc)
                if attempt < self._retries:
                    time.sleep(min(2 ** attempt, 2))
        log.warning("lineage emit dropped after %d attempts", self._retries)
