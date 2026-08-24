# kh-data-lineage — Technical Specification

**Component:** HeatLog (Foundry Data Lineage) · **Package:** `kh-data-lineage`
**Status:** Draft · **July 2026** · Implements [PRD-LINEAGE-SDK-2026-V2](./PDF_Lineage_Tracker_SDK_PRD_v2.md)

This spec turns the PRD's decisions into a concrete design: modules, signatures, the exact OpenLineage mapping, and the test strategy. It is the input to the implementation plan.

---

## 1. Scope

A thin Python SDK that emits one OpenLineage event per **Foundry stage** (`registration`, `chunking`, `review`, `graph`, `rag`) to a self-hosted **Marquez** server. The SDK generates no hashes, opens no DB connections, and never blocks or crashes the calling pipeline. All custom fields ride as OpenLineage **facets**.

**In scope:** event composition, the ontological id, async fire-and-forget emit, void events, a thin `get_lineage` over Marquez's REST API, and a `docker-compose` for Marquez.

**Out of scope (v1):** failure tracking, timings/durations, run status, authentication, a custom backend or schema.

## 2. Architecture

```
Foundry component (Stockyard / Forge / Assay / Lattice / Crucible)
  └─ LineageTracker(...).add_stage("chunking", inputs, outputs, metadata)
       ├─ compose ontological id + build OpenLineage RunEvent (facets)
       └─ AsyncEmitter → ThreadPoolExecutor → openlineage-python HTTP client
            └─ POST /api/v1/lineage → Marquez API → Postgres
```

### 2.1 Module map

| Module | Responsibility |
| --- | --- |
| `kh_data_lineage/__init__.py` | Public exports (`LineageTracker`). |
| `kh_data_lineage/config.py` | Constants + env: `MARQUEZ_URL`, `PRODUCER`, `STAGES`, `PARENT_JOB_NAME`, facet schema URLs. |
| `kh_data_lineage/facets.py` | Custom facets: `HeatlogRunFacet`, `HeatlogVoidRunFacet`. |
| `kh_data_lineage/events.py` | Pure builders: `ontological_id`, `split_dataset`, `build_stage_event`, `build_void_event`. |
| `kh_data_lineage/emit.py` | `AsyncEmitter` — background pool, retry+backoff, swallow-and-warn, atexit flush. |
| `kh_data_lineage/query.py` | `get_lineage` — Marquez REST client (via `requests`). |
| `kh_data_lineage/tracker.py` | `LineageTracker` façade wiring the above together. |

## 3. Runtime & Dependencies

- **Python ≥ 3.11** (matches the Foundry ecosystem; `X | None` typing).
- **`openlineage-python`** (classic `openlineage.client.run` API) — event model + HTTP transport.
- **`requests`** — `get_lineage` queries to Marquez.
- **`attrs`** — custom facet definitions (`@attr.define`; already a transitive dep of `openlineage-python`).
- Packaged as an internal PyPI wheel: `pip install kh-data-lineage`.

## 4. Configuration (`config.py`)

```python
import os

MARQUEZ_URL: str = os.environ.get("HEATLOG_MARQUEZ_URL", "http://localhost:5000")
PRODUCER: str = "https://bitbucket.org/happyfleet/kh-rag-system-data-lineage"
STAGES: frozenset[str] = frozenset({"registration", "chunking", "review", "graph", "rag"})
PARENT_JOB_NAME: str = "foundry_pipeline"
HEATLOG_FACET_SCHEMA: str = f"{PRODUCER}/schemas/heatlog-run-facet.json"
HEATLOG_VOID_FACET_SCHEMA: str = f"{PRODUCER}/schemas/heatlog-void-run-facet.json"
```

The Marquez base URL is the SDK's **only** infrastructure knowledge, env-overridable. No other configuration is read at runtime; init performs no I/O.

## 5. Public API — `LineageTracker`

```python
class LineageTracker:
    def __init__(self, username: str, brand: str, file_hash: str,
                 what: str, why: str, *, run_id: str | None = None,
                 pdf_filename: str | None = None,
                 marquez_url: str = MARQUEZ_URL) -> None: ...

    def add_stage(self, stage_name: str, inputs: list[str],
                  outputs: list[str], metadata: dict | None = None) -> None: ...

    def void(self, reason: str) -> None: ...

    @classmethod
    def void_run(cls, run_id: str, reason: str, username: str, brand: str, *,
                 marquez_url: str = MARQUEZ_URL) -> None: ...

    def get_lineage(self, *, dataset: str | None = None, run_id: str | None = None,
                    brand: str | None = None, include_voided: bool = False) -> dict: ...
```

### 5.1 `__init__` behaviour
1. Validate non-empty strings: `username`, `brand`, `file_hash`, `what`, `why` → else `ValueError`.
2. `self.make = brand.strip().lower()`; store `file_hash`, `username`, `pdf_filename`.
3. `self.run_id = run_id or str(uuid.uuid4())` (accept-else-mint).
4. Construct the OpenLineage HTTP client and wrap it in an `AsyncEmitter`.
5. **No network call.** Purely local.

> **Deviation from PRD §7.3:** `void_run` takes `brand` in addition to `(run_id, reason, username)` — OpenLineage requires a job namespace to emit the `ABORT`, and the namespace is the brand. Documented so implementers don't treat it as a bug.

### 5.2 Validation summary (all at trust boundary, before any network)

| Method | Rule → on failure |
| --- | --- |
| `__init__` | `username/brand/file_hash/what/why` non-empty → `ValueError` |
| `add_stage` | `stage_name in STAGES` → `ValueError`; `inputs`/`outputs` non-empty `list[str]` → `ValueError` |
| `void` / `void_run` | `reason` non-empty → `ValueError` |

## 6. Internal Design

### 6.1 Ontological id (`events.py`)

```python
def ontological_id(make: str, file_hash: str, stage: str) -> str:
    return f"{make.lower()}/{file_hash}/{stage}"
```

Bare `/`-path, lowercase make, **full** 64-hex hash, stage from the fixed vocabulary. Deterministic (`still/3f9a…c7/chunking`).

### 6.2 Dataset naming (`events.py`)

Datasets are path-named so the lineage graph auto-connects. `split_dataset` maps a path/URI to an OpenLineage `(namespace, name)`:

```python
from urllib.parse import urlparse

def split_dataset(path: str) -> tuple[str, str]:
    parsed = urlparse(path)
    if parsed.scheme and parsed.netloc:          # gs://bucket/loaded/x.pdf
        return f"{parsed.scheme}://{parsed.netloc}", parsed.path.lstrip("/")
    if parsed.scheme:                            # spanner:svc.tbl  /  neo4j:still.graph
        return parsed.scheme, parsed.path or parsed.netloc
    return "file", path                          # bare local path
```

| Input | namespace | name |
| --- | --- | --- |
| `gs://bucket/loaded/still/manual.pdf` | `gs://bucket` | `loaded/still/manual.pdf` |
| `spanner:service-ai.still-vectors` | `spanner` | `service-ai.still-vectors` |
| `neo4j:still.manual-graph` | `neo4j` | `still.manual-graph` |

### 6.3 Custom facets (`facets.py`)

```python
import attr
from openlineage.client.facet import BaseFacet
from kh_data_lineage.config import HEATLOG_FACET_SCHEMA, HEATLOG_VOID_FACET_SCHEMA

@attr.define
class HeatlogRunFacet(BaseFacet):
    ontologicalId: str
    make: str
    fileHash: str
    filename: str | None
    what: str
    why: str
    username: str
    metadata: dict
    @staticmethod
    def _get_schema() -> str: return HEATLOG_FACET_SCHEMA

@attr.define
class HeatlogVoidRunFacet(BaseFacet):
    reason: str
    voidedBy: str
    @staticmethod
    def _get_schema() -> str: return HEATLOG_VOID_FACET_SCHEMA
```

`BaseFacet` injects `_producer` / `_schemaURL` on serialization. Facet keys on the run: `"heatlog"` and `"heatlog_void"`.

### 6.4 Event construction (`events.py`)

**Stage event** (`eventType=COMPLETE`): child run per stage, linked to the parent (Foundry pipeline) run via `ParentRunFacet`.

```python
from datetime import datetime, timezone
from openlineage.client.run import RunEvent, RunState, Run, Job, InputDataset, OutputDataset
from openlineage.client.facet import ParentRunFacet
from kh_data_lineage.config import PRODUCER, PARENT_JOB_NAME

def build_stage_event(*, make, file_hash, filename, what, why, username,
                      parent_run_id, stage, inputs, outputs, metadata,
                      stage_run_id) -> RunEvent:
    parent = ParentRunFacet.create(runId=parent_run_id, namespace=make, name=PARENT_JOB_NAME)
    run = Run(runId=stage_run_id, facets={
        "parent": parent,
        "heatlog": HeatlogRunFacet(ontological_id(make, file_hash, stage), make,
                                   file_hash, filename, what, why, username, metadata or {}),
    })
    job = Job(namespace=make, name=stage)
    return RunEvent(
        eventType=RunState.COMPLETE,
        eventTime=datetime.now(timezone.utc).isoformat(),
        run=run, job=job, producer=PRODUCER,
        inputs=[InputDataset(*split_dataset(p)) for p in inputs],
        outputs=[OutputDataset(*split_dataset(p)) for p in outputs],
    )
```

**Void event** (`eventType=ABORT`): targets the **parent** run directly.

```python
def build_void_event(*, make, parent_run_id, reason, voided_by) -> RunEvent:
    run = Run(runId=parent_run_id, facets={"heatlog_void": HeatlogVoidRunFacet(reason, voided_by)})
    return RunEvent(
        eventType=RunState.ABORT,
        eventTime=datetime.now(timezone.utc).isoformat(),
        run=run, job=Job(namespace=make, name=PARENT_JOB_NAME), producer=PRODUCER,
        inputs=[], outputs=[],
    )
```

> The parent run node is created lazily by Marquez from the `ParentRunFacet` reference (and by the void `ABORT`). v1 does **not** emit an explicit parent START/COMPLETE.

### 6.5 Async emitter (`emit.py`)

Guarantees "never block or crash the pipeline" and "retry 3× with a stable runId."

```python
import atexit, logging, time
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("kh_data_lineage")

class AsyncEmitter:
    def __init__(self, client, *, max_workers: int = 4, retries: int = 3):
        self._client, self._retries = client, retries
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        atexit.register(self._pool.shutdown, wait=True)      # flush pending on exit

    def emit(self, run_event) -> None:
        self._pool.submit(self._emit_with_retry, run_event)   # fire-and-forget

    def _emit_with_retry(self, run_event) -> None:            # SAME event across retries → stable runId
        for attempt in range(1, self._retries + 1):
            try:
                self._client.emit(run_event); return
            except Exception as exc:                          # never propagate to the pipeline
                log.warning("lineage emit failed (attempt %d/%d): %s", attempt, self._retries, exc)
                if attempt < self._retries:
                    time.sleep(min(2 ** attempt, 2))          # exp backoff, capped 2s
        log.warning("lineage emit dropped after %d attempts", self._retries)
```

`_emit_with_retry` is synchronous and directly unit-testable. `emit()` submits it to the pool. The same `run_event` object (and its `runId`) is reused across retries.

### 6.6 `get_lineage` (`query.py`)

Thin wrapper over Marquez's REST API using `requests`. v1 supports the native handles and returns raw JSON.

```python
import requests
from kh_data_lineage.config import MARQUEZ_URL

def get_lineage(*, dataset=None, run_id=None, brand=None,
                include_voided=False, marquez_url=MARQUEZ_URL) -> dict:
    if dataset:
        ns, name = split_dataset(dataset)
        r = requests.get(f"{marquez_url}/api/v1/lineage",
                         params={"nodeId": f"dataset:{ns}:{name}"}, timeout=10)
    elif run_id:
        r = requests.get(f"{marquez_url}/api/v1/jobs/runs/{run_id}", timeout=10)
    elif brand:
        r = requests.get(f"{marquez_url}/api/v1/namespaces/{brand}/jobs", timeout=10)
    else:
        raise ValueError("one of dataset / run_id / brand is required")
    r.raise_for_status()
    data = r.json()
    return data if include_voided else _drop_voided(data)
```

`_drop_voided` filters graph nodes/runs whose facets contain `heatlog_void`. For the PoC this is best-effort over the returned payload; exact traversal is finalised against a live Marquez response.

## 7. Guarantees & Error Handling

- **Pipeline safety:** every network path runs in the pool; `_emit_with_retry` swallows all exceptions. A lineage outage degrades to warning logs — the Foundry pipeline is never affected. `get_lineage` is the only synchronous call and may raise (it is a read tool, not on the pipeline path).
- **Validation** happens before any network I/O and raises `ValueError` with a clear message.
- **Idempotency:** retries reuse the same stage `runId`, so a retried emit updates the same Marquez run rather than duplicating it.
- **Durability on exit:** the `atexit` pool shutdown (`wait=True`) flushes queued emits before the process ends.

## 8. Testing Strategy

Pure functions and validation carry the logic; the network is thin. Unit tests (no live Marquez) cover:

| Test area | Cases |
| --- | --- |
| `ontological_id` | lowercases make; exact `make/hash/stage` string |
| `split_dataset` | `gs://bucket/x`, `spanner:a.b`, `neo4j:a`, bare path |
| `HeatlogRunFacet` | fields present; `_producer`/`_schemaURL` on serialization |
| `build_stage_event` | `job.namespace==make`, `job.name==stage`, `COMPLETE`, parent+heatlog facets, dataset counts |
| `build_void_event` | `ABORT`, `heatlog_void` facet, parent job |
| `LineageTracker.__init__` | missing `what`/`why` → `ValueError`; `run_id` minted when omitted |
| `add_stage` | unknown stage → `ValueError`; empty inputs/outputs → `ValueError`; emits one event |
| `AsyncEmitter._emit_with_retry` | success once; retries then succeeds; always-fails → swallowed, N attempts |

`add_stage`/emitter tests inject a **fake client** (records events, or raises) — no HTTP. A single optional integration test (Phase 3) emits to a local Marquez and reads it back; marked manual.

## 9. Phase 1 — Marquez deployment

`docker-compose.yml` running the three official images against a bundled Postgres:

- `marquezproject/marquez` (API, `:5000` — remap to `:9000` on macOS), `marquezproject/marquez-web` (`:3000`), `postgres:15` (`marquez-db`).
- Env: `POSTGRES_DB=marquez`, `POSTGRES_USER=marquez`, `POSTGRES_PASSWORD=marquez`; API `MARQUEZ_CONFIG`/env wired to the db.
- Runs on a VPC-private GCE VM. Postgres volume on a mounted disk (PoC); migrate to Cloud SQL before real data.
- Acceptance: `POST /api/v1/lineage` with a sample event returns 201 and the event renders in the web UI.

## 10. Open Items

- **`run_id` propagation across components** (PRD Q7) — how the Foundry-pipeline run id is minted once and shared. PoC-undecided; the SDK's accept-else-mint keeps it working per-component in the meantime.
- **`_drop_voided` traversal** — finalise against a live Marquez lineage payload.
- **Parent run event** — confirm Marquez lazily materialises the parent from the facet; emit an explicit parent event only if it does not.

## 11. File/Deliverable Summary

```
kh_data_lineage/
  __init__.py     config.py     facets.py     events.py
  emit.py         query.py      tracker.py
tests/
  test_events.py  test_facets.py  test_emit.py  test_tracker.py
docker-compose.yml            # Phase 1 — Marquez
pyproject.toml                # package metadata + deps
```

---
*HeatLog — kh-data-lineage technical spec | Confidential — Internal Use Only*
