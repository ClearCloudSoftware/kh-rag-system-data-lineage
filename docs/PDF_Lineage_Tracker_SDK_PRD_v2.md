# PDF Lineage Tracker SDK — HeatLog

**Product Requirement Document**

*Version 2.0 | July 2026 | Status: Draft for Review*

| Field | Value |
| --- | --- |
| Document ID | PRD-LINEAGE-SDK-2026-V2 |
| Supersedes | PRD-LINEAGE-SDK-2026-V1 |
| Repo | `happyfleet/kh-rag-system-data-lineage` (HeatLog) |
| Package | `kh-data-lineage` |
| Component | Foundry → HeatLog (Data Lineage) |

---

## 0. What changed from v1 (and why)

v1 described a bespoke backend, a custom Postgres schema, a filename-derived hash the SDK would generate, and a scope limited to Forge's internal chunking steps. Grilling against the actual Foundry ecosystem (Stockyard, Forge, Lattice, Marquez/OpenLineage) collapsed most of that. The decisions below supersede v1; the rest of this document is written to match them.

| # | v1 said | v2 decision |
| --- | --- | --- |
| 1 | SDK connects to Cloud SQL on init | **SDK speaks HTTP only.** It opens zero DB connections; init is fully local. |
| 2 | SDK generates `run_hash = SHA-256(filename)[:16]` | **SDK generates no hashes.** Identity is received from upstream (Stockyard `file_hash`, Forge/Foundry `run_id`). |
| 3 | Identity = truncated filename hash | **Ontological id** = `make/hash/stage` — deterministic, content-addressable, full 64-hex Stockyard hash. |
| 4 | Deterministic hash as PK (breaks re-processing) | Deterministic id **+ a run dimension** (`run_id`); re-processing = new run, same id. |
| 5 | Records overwritten/updated | **Append-only, immutable, time-ordered.** Nothing is mutated or deleted. |
| 6 | — | Operator **`what` + `why`** required at init (the audit value the pipeline doesn't capture). |
| 7 | `update_stage` (PATCH) + `delete_stage` (DELETE) | **Both dropped.** Corrections = append; retractions = a **void event** (`ABORT`). |
| 8 | Track status, duration, errors | **Out of scope for v1.** Track only *what a file went through* and *what it output*. |
| 9 | Scoped to Forge's internal chunking steps | **Foundry-wide.** Stages are the Foundry *components*; **Forge is one `chunking` step**. |
| 10 | Custom REST backend + custom schema | **Adopt Marquez** (reference OpenLineage server) + `openlineage-python`. No custom backend. |
| 11 | Cloud Run primary, Compute Engine fallback | **GCE VM + docker-compose** (Marquez isn't a scale-to-zero app); Cloud Run dropped. |
| 12 | `page_count`, `document_id`, etc. tracked by SDK | SDK **receives** `file_hash`/`run_id`, **composes** the id; `document_id` dropped, `filename` kept. |
| 13 | — | Per-brand **job namespace**; path-named **datasets**; `ParentRunFacet` groups the Foundry pipeline run. |
| 14 | 200 ms latency budget | **Dropped** — emits are fire-and-forget; the budget is meaningless. |
| 15 | Identity = username (fake auth) | `username` is an **attribution facet, not authentication**; Marquez sits on a private VPC. |

---

## 1. Executive Summary

A document entering Foundry flows through five components — **Stockyard** (registration) → **Forge** (chunking) → **Assay** (review) → **Lattice** (graph) → **Crucible** (RAG). Today there is no durable, queryable record of **what processes a file has been through and what each produced**. HeatLog fills that gap.

HeatLog is a thin Python SDK (`kh-data-lineage`) that wraps [OpenLineage](https://openlineage.io) (via `openlineage-python`) and emits one standard lineage event per Foundry stage. Each component imports the SDK, initialises it with a handful of already-known values, and calls one method for its step. Events are sent over HTTP to a self-hosted **Marquez** server, which stores them in Postgres and renders a lineage graph.

The SDK generates no hashes and opens no database connections. It composes a meaningful **ontological id** from identity that already exists upstream (Stockyard's content hash, the brand, the stage) and rides all custom fields as OpenLineage **facets**. Because the wire format is standard OpenLineage, the backend is swappable — Marquez today, anything OL-compatible later — with zero pipeline-code changes.

## 2. Problem Statement

When a PDF moves through Foundry, there is no centralised record of:

- Which Foundry processes (stages) the file has been through
- What the input and output artifacts were at each step
- Whether — and why — a file has been re-processed, and by whom

Without this, debugging is slow, re-processing decisions are undocumented, and there is no audit trail. The solution must add near-zero engineering overhead: if it is complex to use, engineers will skip it.

**Explicitly out of scope for v1:** failure tracking, stage timings/durations, and run status. HeatLog v1 records *what completed and what it produced* — a stage that crashes simply does not appear (it produced no output, so there is nothing to record). These can be added later without changing the identity model.

## 3. Goals & Non-Goals

### 3.1 Goals

- A Python SDK usable in under five minutes: import, init, one call per stage.
- Record, per Foundry stage: the process name, its input artifacts, its output artifacts, and optional metadata.
- Give every artifact a deterministic, content-addressable **ontological id** that joins to the rest of Foundry (Stockyard hash, Lattice qualifiers).
- Capture operator intent (`what` + `why`) for every run — the audit context the pipeline does not store.
- Emit standard OpenLineage events to a self-hosted Marquez backend (Postgres).
- Require no cloud credentials in pipeline code — the SDK only speaks HTTP.

### 3.2 Non-Goals

- Not a general-purpose lineage tool — scoped to the Foundry PDF document pipeline for v1.
- Does not track failures, timings, or run status in v1 (see §2).
- Does not model Forge's *internal* chunking sub-steps — Forge is a single `chunking` stage at the Foundry altitude.
- Does not build a UI — Marquez already provides the lineage graph.
- No real-time streaming or event-driven triggers in v1.
- No authentication layer — `username` is attribution only; the backend is network-isolated.

## 4. Foundry Stages & What We Track

HeatLog records one lineage event per **Foundry component boundary**. Stage names are a **fixed vocabulary** (validated by the SDK — a typo is rejected up front, not corrected later). Forge's internal steps (`pdf_load`, `extract_toc`, …) are Forge's private business and are *not* tracked here.

| # | `stage_name` | Component | Input → Output | Optional metadata |
| --- | --- | --- | --- | --- |
| 1 | `registration` | **Stockyard** | Raw PDF → registered document (hash assigned) | `page_count`, `file_size_mb` |
| 2 | `chunking` | **Forge** | Registered PDF → chunk files | `chunk_count` |
| 3 | `review` | **Assay** | Chunk files → approved chunks | `records_approved`, `taxonomy_tags` |
| 4 | `graph` | **Lattice** | Approved chunks → graph nodes | `nodes_created`, `edges_created` |
| 5 | `rag` | **Crucible** | Approved chunks → vector store location | `vectors_written` |

Note the DAG shape: `review`'s output feeds **both** `graph` and `rag`. Path-named datasets (§8) make the lineage graph connect these automatically.

## 5. Identity & Authentication

The SDK receives identity; it never mints hashes or holds credentials. Every Foundry component instantiates a tracker with the **same** `file_hash` and Foundry-pipeline `run_id`, so all five stages hang off one shared identity.

| Value | Type | Source | Role |
| --- | --- | --- | --- |
| `username` | `str` | operator | Attribution (a facet, **not** authentication) |
| `brand` | `str` | Stockyard metadata | The `make` in the ontological id + the OL job namespace |
| `file_hash` | `str` (sha256, 64 hex) | **Stockyard** | The document's content identity |
| `run_id` | `str` (UUID) | **Foundry pipeline** (optional) | The pipeline-execution / parent-run id; minted if absent |
| `pdf_filename` | `str` | operator (optional) | Human-friendly attribute for lookup/display |
| `what` | `str` | operator (**required**) | What this run does to the file |
| `why` | `str` | operator (**required**) | Why the run is happening |

There is **no registry lookup** on init (v1). The SDK's only bootstrap infrastructure is the Marquez base URL, baked into the package (env-overridable). `username` is self-asserted and used purely for attribution; the backend is protected by network isolation, not by the SDK (§9, §10).

## 6. Run Identity & The Ontological ID

HeatLog does **not** generate identity — that happens upstream. Stockyard computes the content `file_hash`; the Foundry pipeline assigns the `run_id`. The SDK **composes** a human-readable, decodable identifier from parts it is handed.

### 6.1 The ontological id

```
still / 3f9a…c7 (full 64-hex sha256) / chunking
└make┘ └──── Stockyard file_hash ────┘ └─ stage ─┘
```

- **Format:** bare `/`-delimited path. `make` lowercased. **Full** 64-hex hash (never truncated — truncation was v1's collision bug and would break the join to Stockyard). Stage from the fixed vocabulary.
- **Grain:** one ontological id per **stage event**. The `make/hash` prefix is the document's stable identity; each Foundry stage extends it.
- **Deterministic & content-addressable:** the same file at the same stage always yields the same id. This is the point — Stockyard, Forge, and Lattice all key off `make + hash`, so a deterministic id is what lets HeatLog *join* to the rest of Foundry.

### 6.2 Re-processing (the run dimension)

A deterministic id cannot, by itself, distinguish re-runs. So identity has two axes:

- **Ontological id** answers *what this is* (this file, at this stage). Deterministic.
- **`run_id`** answers *which execution*. A re-run reuses the ontological id but gets a new `run_id`.

Every event is **append-only and immutable**, ordered by time. Re-processing the same file produces a fresh set of events under a new `run_id`; nothing is overwritten. The full history of a file is every event under `make/hash/…`, in time order. In OpenLineage terms, `run_id` is the **parent** run (one document's pass through Foundry) and each stage is a child run — see §8.

## 7. SDK Interface Specification

Four public methods. Design principle: **one call per stage**, no boilerplate. The SDK is a thin facade over `openlineage-python` — it builds the `RunEvent`, attaches facets, and emits asynchronously so it can never block or crash the pipeline.

### 7.1 Initialisation

```python
from kh_data_lineage import LineageTracker

tracker = LineageTracker(
    username="jdoe",
    brand="still",
    file_hash="3f9a…c7",              # from Stockyard
    what="initial processing",         # required
    why="new manual onboarded",        # required
    run_id="a0d1…",                    # Foundry pipeline run; minted (uuid4) if omitted
    pdf_filename="manual.pdf",         # optional
)
```

Init is **fully local**: it validates `what`/`why` are non-empty, lowercases `make`, defaults `run_id` to a fresh UUID, and constructs an OpenLineage HTTP client. **No network call.** The constructor refuses to build a tracker without `what` and `why`, so nothing is ever logged un-justified.

### 7.2 add_stage()

```python
tracker.add_stage(stage_name, inputs, outputs, metadata={})
```

Called once by a component for its Foundry step, after it completes. Emits one immutable OpenLineage `COMPLETE` event.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `stage_name` | `str` | Yes | One of the five Foundry stages (validated; unknown → error) |
| `inputs` | `list[str]` | Yes | Input artifact paths/identifiers |
| `outputs` | `list[str]` | Yes | Output artifact paths/identifiers |
| `metadata` | `dict` | No | Custom key-values (e.g. `chunk_count`) |

The SDK composes `ontological_id = f"{make}/{file_hash}/{stage_name}"`, mints a stage `runId`, links it to the parent `run_id` via `ParentRunFacet`, wraps inputs/outputs as OL Datasets, attaches the `heatlog` facet, and emits in a background thread.

### 7.3 void()

```python
tracker.void(reason)                                   # voids the current run
LineageTracker.void_run(run_id, reason, username)      # voids any past run (classmethod)
```

Retracts an experiment or junk run **without deleting anything**. Emits an immutable OpenLineage `ABORT` event on the parent run, carrying a void facet (`reason`, `voided_by`). The run and its events remain in the log forever — you can always see that it *was* retracted, by whom, and why. `get_lineage` hides voided runs by default.

### 7.4 get_lineage()

```python
tracker.get_lineage(dataset=None, run_id=None, brand=None, include_voided=False)
```

A thin wrapper over Marquez's REST API. Query by a native Marquez handle:

- **`dataset`** (a path) → that file's lineage graph — *the core "what did this file go through, and what did it output" query.*
- **`run_id`** → the pipeline execution's stage-runs and datasets.
- **`brand`** → list runs/jobs in the namespace.

Returns raw Marquez lineage JSON (v1). Voided runs are filtered out client-side unless `include_voided=True`. Lookup by `file_hash`/`filename` is deferred to v1's Stockyard resolution or the Marquez UI (identity lives in facets, which Marquez's API does not index).

## 8. Data Model — OpenLineage Events & Facets

HeatLog stores nothing of its own. It emits standard OpenLineage `RunEvent`s; **Marquez** persists them in its own Postgres schema (`jobs`, `datasets`, `runs`, `lineage_events`, facet tables). Our model maps onto OpenLineage as follows:

| Our concept | OpenLineage entity | namespace | name |
| --- | --- | --- | --- |
| A file / artifact | **Dataset** | storage root (`gs://<bucket>`, `spanner`, `neo4j`) | object path (`registered/still/manual.pdf`) |
| A Foundry stage | **Job** | **brand** (`still`, `klm`, …) | stage (`chunking`) |
| One stage execution | **Run** | — | minted `runId` (UUID) |
| The Foundry pipeline run | **`ParentRunFacet`** | brand | `foundry_pipeline` |

- **Datasets are path-named**, so one stage's output path equals the next stage's input path and the lineage graph **auto-connects**.
- **Jobs are namespaced per brand** — at thousands of PDFs per brand, this keeps the Marquez UI navigable.
- **All custom fields ride as facets** — nothing is lost. The `heatlog` run facet carries `ontologicalId`, `make`, `fileHash`, `filename`, `what`, `why`, `username`, and `metadata`.
- **eventType is `COMPLETE` only** (no `START`/`FAIL` — timings and failures are out of scope). **void** emits `ABORT`.

### 8.1 Sample `RunEvent` (stage 2, `chunking`)

```json
{
  "eventType": "COMPLETE",
  "eventTime": "2026-07-01T10:15:30.000Z",
  "producer": "https://bitbucket.org/happyfleet/kh-rag-system-data-lineage",
  "run": {
    "runId": "b1e2c3d4-…",
    "facets": {
      "parent": {
        "run": { "runId": "a0d1…" },
        "job": { "namespace": "still", "name": "foundry_pipeline" }
      },
      "heatlog": {
        "ontologicalId": "still/3f9a…c7/chunking",
        "make": "still",
        "fileHash": "3f9a…c7",
        "filename": "manual.pdf",
        "what": "initial processing",
        "why": "new manual onboarded",
        "username": "jdoe",
        "metadata": { "chunk_count": 34 }
      }
    }
  },
  "job": { "namespace": "still", "name": "chunking" },
  "inputs":  [ { "namespace": "gs://bucket", "name": "registered/still/manual.pdf" } ],
  "outputs": [ { "namespace": "gs://bucket", "name": "chunks/still/manual_chunk_0001.json" } ]
}
```

## 9. Backend Architecture — Marquez

The backend is **Marquez**, the reference OpenLineage server. HeatLog builds no backend service and defines no schema.

### 9.1 Topology

Marquez is a three-container system (via `docker-compose`):

| Container | Role | Port |
| --- | --- | --- |
| `marquez-api` | OpenLineage ingestion + query REST API (Java/Dropwizard) | 5000 (+5001 admin) |
| `marquez-web` | Lineage graph UI (React) | 3000 |
| `marquez-db` | Postgres metadata store | 5432 |

The SDK's `openlineage-python` HTTP transport posts `RunEvent`s to `POST /api/v1/lineage`; `get_lineage` reads from the same API.

### 9.2 Hosting

| Option | Service | When |
| --- | --- | --- |
| **PoC (recommended)** | **GCE VM** running `docker-compose` (all three containers), on a **private VPC** | Fastest path to a working Marquez; least translation |
| Production | GKE via the official Marquez Helm chart, + **Cloud SQL** for Postgres | Scale, managed DB, HA |

Cloud Run is **not** used — Marquez is a multi-container, JVM, always-on service, the opposite of a scale-to-zero function. **Database:** the bundled `marquez-db` Postgres on a mounted disk is fine for the first spin-up; migrate to **Cloud SQL** before real data accumulates (thousands of PDFs per brand will fill it quickly).

### 9.3 Security

Marquez ships with no authentication. It is placed on a **private VPC**, reachable only from the pipeline environment — nothing public-facing. `username` is an attribution facet, not a credential. Real authn (IAP / API gateway) is a post-PoC concern.

## 10. Non-Functional Requirements

| Requirement | Specification |
| --- | --- |
| Async execution | `add_stage`/`void` emit on a bounded background thread pool. A lineage failure must **never** crash or block the pipeline. |
| Failure handling | Emit errors are swallowed and logged as a local warning; retry 3× with exponential backoff. The **same stage `runId` is reused across retries**, so a retry updates the same run rather than duplicating it. |
| No cloud auth overhead | The SDK opens no DB connections and needs no service-account keyfiles or gcloud CLI. It only speaks HTTP to Marquez. |
| Input validation | `what`/`why` non-empty (init); `inputs`/`outputs` non-empty string lists; `stage_name` in the fixed vocabulary — all validated before any network call. |
| Immutability | Events are append-only. Corrections are new events (time-order wins); retractions are `ABORT` (void) events. Nothing is mutated or deleted. |
| Packaging | Distributed as an internal PyPI package (`pip install kh-data-lineage`), depending on `openlineage-python`. |

## 11. Implementation Plan & Phases

### Phase 1 — Deploy Marquez
- Stand up Marquez via `docker-compose` on a VPC-private GCE VM (api + web + db).
- Verify `POST /api/v1/lineage` ingestion and the UI render an event end-to-end.
- (Plan the Cloud SQL migration path.)

### Phase 2 — Build the SDK
- Implement `LineageTracker` (`__init__`, `add_stage`, `void`/`void_run`, `get_lineage`) as a facade over `openlineage-python`.
- Compose the ontological id; build `RunEvent`s with `ParentRunFacet` + the `heatlog` facet; path-name datasets.
- Async emit: bounded thread pool, swallow-and-warn, 3× backoff, stable runId across retries.
- Validate `what`/`why`, inputs/outputs, and the Foundry-stage vocabulary.

### Phase 3 — Package & Pilot
- Package for internal PyPI; write the engineer-facing quickstart + method reference.
- Run an end-to-end test across all five Foundry stages.
- Onboard one pilot component (e.g. Forge's `chunking`) for feedback, then widen.

## 12. Example Usage

The flow below shows all five stages for one document. **In production each `add_stage` call is made by the respective Foundry component** (Stockyard, Forge, Assay, Lattice, Crucible), each instantiating a tracker with the *same* `file_hash` and Foundry-pipeline `run_id`.

```python
from kh_data_lineage import LineageTracker

tracker = LineageTracker(
    username="jdoe",
    brand="still",
    file_hash="3f9a…c7",                 # from Stockyard
    run_id="a0d1…",                      # Foundry pipeline run (optional)
    what="initial processing",
    why="new manual onboarded",
    pdf_filename="manual.pdf",
)

# Stage 1 — Stockyard: registration
tracker.add_stage("registration",
    inputs=["gs://bucket/raw/still/manual.pdf"],
    outputs=["gs://bucket/registered/still/manual.pdf"],
    metadata={"page_count": 142, "file_size_mb": 8.4})

# Stage 2 — Forge: chunking
tracker.add_stage("chunking",
    inputs=["gs://bucket/registered/still/manual.pdf"],
    outputs=["gs://bucket/chunks/still/manual_chunk_0001.json"],
    metadata={"chunk_count": 34})

# Stage 3 — Assay: review
tracker.add_stage("review",
    inputs=["gs://bucket/chunks/still/manual_chunk_0001.json"],
    outputs=["gs://bucket/approved/still/manual_chunk_0001.json"],
    metadata={"records_approved": 34, "taxonomy_tags": ["engine", "brakes", "safety"]})

# Stage 4 — Lattice: graph
tracker.add_stage("graph",
    inputs=["gs://bucket/approved/still/manual_chunk_0001.json"],
    outputs=["neo4j:still.manual-graph"],
    metadata={"nodes_created": 128, "edges_created": 342})

# Stage 5 — Crucible: rag
tracker.add_stage("rag",
    inputs=["gs://bucket/approved/still/manual_chunk_0001.json"],
    outputs=["spanner:service-ai.still-manual-vectors"],
    metadata={"vectors_written": 34})

# Later — retract a junk experiment (nothing is deleted)
# LineageTracker.void_run("a0d1…", reason="wrong taxonomy model", username="jdoe")
```

## 13. Open Questions & Decisions

| # | Question | Status |
| --- | --- | --- |
| 1 | `asyncio`/`await` support in addition to background threads? | Deferred to v2 — threads are sufficient. |
| 2 | Retention policy for lineage events? | Keep indefinitely for v1 (Marquez default). |
| 3 | Multiple brands per engineer? | Yes — one tracker per `(brand, file)`; brand is per-run. |
| 4 | Pagination on `get_lineage`? | Marquez's API paginates; no extra work needed. |
| 5 | Package name | **Resolved** — `kh-data-lineage` (`from kh_data_lineage import LineageTracker`). |
| 6 | Parent-run scope | **Resolved** — the full Foundry pipeline pass (Stockyard→…→Crucible). |
| 7 | **How is the Foundry-pipeline `run_id` propagated across components?** | **OPEN** — must be minted once (at `registration`) and shared downstream, but the mechanism (stored in Stockyard? passed via orchestration?) is undecided. This is a PoC; we don't yet know 100%. |

---

## Appendix A — Decision Log

| ID | Decision |
| --- | --- |
| D1 | SDK speaks HTTP only; opens no DB connection; init is fully local (no registry call in v1). |
| D2 | SDK generates no hashes — identity is received (Stockyard `file_hash`, Foundry `run_id`). |
| D3 | Ontological id = `make/hash/stage`, bare `/`-path, full 64-hex hash, lowercase make, one per stage event. |
| D4 | Deterministic id + `run_id` dimension: re-processing = new run, same id, nothing overwritten. |
| D5 | Append-only, immutable, time-ordered log. |
| D6 | `what` + `why` (plain text) required at init; SDK refuses to init without them. |
| D7 | `update_stage`/`delete_stage` dropped; corrections = append (time-order wins). |
| D8 | Retractions = a **void** event (`ABORT` + facet); `void()` + `void_run()`; hidden by default in `get_lineage`. |
| D9 | Failures, timings, run status **out of scope** for v1; `add_stage` is a simple post-hoc call. |
| D10 | Wrap OpenLineage (`openlineage-python`); emit standard `RunEvent`s over HTTP. |
| D11 | Adopt **Marquez** as the backend; no custom service, no custom schema. |
| D12 | Model: dataset = file (storage namespace, path name); job = stage (brand namespace); run = per-stage; `ParentRunFacet` = Foundry pipeline run. |
| D13 | Path-named datasets → the lineage graph auto-connects. |
| D14 | `get_lineage` = thin wrapper over Marquez REST (by dataset / run_id / brand). |
| D15 | Host Marquez on a VPC-private GCE VM + docker-compose (Cloud SQL for production); Cloud Run dropped; 200 ms latency NFR dropped; `username` = attribution, not auth. |
| D16 | Stages = **Foundry components** (`registration`/`chunking`/`review`/`graph`/`rag`); **Forge = one `chunking` step**; the SDK is Foundry-wide, instrumented by each component. |
| D17 | Package name = `kh-data-lineage`. |

---

*HeatLog — PDF Lineage Tracker SDK | PRD-LINEAGE-SDK-2026-V2 | Confidential — Internal Use Only*
