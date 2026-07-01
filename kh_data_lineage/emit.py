import atexit, logging, time
from concurrent.futures import ThreadPoolExecutor
from openlineage.client import OpenLineageClient
from openlineage.client.transport.http import HttpConfig, HttpTransport

log = logging.getLogger("kh_data_lineage")

def _build_client(marquez_url: str) -> OpenLineageClient:
    return OpenLineageClient(transport=HttpTransport(HttpConfig(url=marquez_url)))

class AsyncEmitter:
    def __init__(self, client, *, max_workers: int = 4, retries: int = 3):
        self._client, self._retries = client, retries
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        atexit.register(self._pool.shutdown, wait=True)

    def emit(self, run_event) -> None:
        self._pool.submit(self._emit_with_retry, run_event)

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
