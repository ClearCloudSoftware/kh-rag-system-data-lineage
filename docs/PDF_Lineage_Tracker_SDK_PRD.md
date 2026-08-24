# PDF Lineage Tracker SDK

**Product Requirement Document**

*Version 1.0 | June 2026 | Status: Draft for Review*

| Field | Value |
| --- | --- |
| Document ID | PRD-LINEAGE-SDK-2026-V1 |

---

## 1. Executive Summary

Data engineers processing PDF documents through multi-stage pipelines currently have no lightweight, standardised way to track data lineage — that is, to record what happened to a file, when it happened, and what state it moved into at each step.

This document defines the requirements for the PDF Lineage Tracker SDK: an internal Python package that wraps the OpenLineage open standard and exposes a dead-simple interface for pipeline developers. Engineers import the library, initialise it with their username, and call a single method at each stage. The SDK handles everything else: payload generation, run ID creation, timestamping, database lookups, and REST API delivery.

The backend service that the SDK talks to will be hosted on Google Cloud Run (with Compute Engine as an always-on fallback), and all lineage records will be persisted in a managed Cloud SQL PostgreSQL instance.

## 2. Problem Statement

Today, when a PDF passes through the processing pipeline, there is no centralised record of:

- Which stage the file is currently in
- What the input and output file paths were at each step
- Whether a stage completed successfully, failed, or is still running
- How long each stage took
- How many chunks or pages were produced
- Whether a file has been re-processed, and why

Without this visibility, debugging failures is slow, re-processing decisions are manual, and audit trails are non-existent. The solution must not add meaningful engineering overhead — if it is complex to use, engineers will skip it.

## 3. Goals & Non-Goals

### 3.1 Goals

- Provide a Python SDK that engineers can import and use in under five minutes
- Track every stage of the PDF chunking pipeline with a single method call per stage
- Record stage name, status, input/output paths, timestamps, errors, and custom metadata
- Identify each pipeline run with a unique hash derived from the PDF filename
- Store all lineage events in Cloud SQL PostgreSQL
- Host the backend service on Cloud Run (serverless), with Compute Engine as a fallback
- Authenticate engineers via username — no cloud credentials required

### 3.2 Non-Goals

- This SDK is not a general-purpose lineage tool — it is scoped to the PDF chunking pipeline only for v1
- It will not replace or replicate a full OpenLineage server — it wraps the standard and writes to our own backend
- It will not provide a UI or dashboard in v1 — records are queryable via SQL
- It will not support real-time streaming or event-driven triggers in v1

## 4. Pipeline Stages & What We Track

The PDF processing pipeline consists of five sequential stages. The SDK must record a lineage event at each stage boundary.

| Stage | Input | Output | What to Record |
| --- | --- | --- | --- |
| 1. PDF Load | Raw PDF path (GCS) | Loaded file object | File size, page count, load duration, status |
| 2. Extract TOC | Loaded PDF object | TOC structure (JSON) | TOC entries found, extraction duration, status |
| 3. Chunk by TOC | TOC + PDF | Chunk files (GCS) | Chunk count, output paths, chunking duration, status |
| 4. Clean & Taxonomy | Chunk files | Cleaned chunks + taxonomy labels | Records cleaned, taxonomy tags applied, duration, status |
| 5. Upload to RAG DB | Cleaned chunks | Vector store location | Vectors written, RAG DB path, upload duration, status |

## 5. Identity & Authentication

Engineers authenticate with a plain string parameter — no cloud service accounts, no keyfiles, no gcloud CLI setup required in application code.

| Parameter | Type | Description | Example |
| --- | --- | --- | --- |
| username | str | Engineer's internal identifier | jdoe |

On initialisation, the SDK queries the Cloud SQL registry to resolve the engineer's namespace and target API endpoint. This means engineers never hardcode infrastructure details in their pipeline scripts.

## 6. Run Identification & Hashing Strategy

Every pipeline execution receives a unique run hash. This hash is the primary key for all lineage events belonging to that execution.

### 6.1 Hash Generation

The run hash is derived from:

- PDF filename (normalised, lowercase)

The hash is generated using SHA-256 over the concatenated string of these values. The first 16 characters of the hex digest are used as the run ID for readability.

## 7. SDK Interface Specification

The SDK exposes a single class with four public methods. The design principle is: one line of code per stage.

### 7.1 Initialisation

```python
from lineage_sdk import LineageTracker

tracker = LineageTracker(username="jdoe", brand="still")
```

On initialisation the SDK will:

- Connect to Cloud SQL and look up the engineer's namespace and API endpoint
- Generate the run hash from filename
- Store the run hash internally for all subsequent method calls

### 7.2 add_stage()

```python
tracker.add_stage(stage_name, inputs, outputs, metadata={})
```

Called once per pipeline stage. Records a COMPLETE event to the lineage backend. The SDK automatically injects the run hash, timestamps, and OpenLineage schema fields.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| stage_name | str | Yes | Human-readable stage label (e.g. chunk_by_toc) |
| inputs | list[str] | Yes | List of input file paths or identifiers |
| outputs | list[str] | Yes | List of output file paths or identifiers |
| metadata | dict | No | Custom key-value pairs (e.g. chunk_count, page_count) |

### 7.3 update_stage()

```python
tracker.update_stage(stage_id, new_name=None, metadata=None)
```

Issues a PATCH request to update the display name or metadata of a previously recorded stage. Used to correct labelling errors without deleting the record.

### 7.4 delete_stage()

```python
tracker.delete_stage(stage_id)
```

Issues a DELETE request to remove a lineage record. Intended for cleaning up test runs and experiments, not for production use.

### 7.5 get_lineage()

```python
tracker.get_lineage(pdf_filename=None, run_hash=None)
```

Queries the backend and returns all lineage events for a given PDF filename or run hash. Returns a list of stage records as Python dicts. Useful for debugging and audit purposes.

## 8. Data Model (Cloud SQL PostgreSQL)

Two tables will store all lineage data.

### 8.1 pipeline_runs

| Column | Type | Description |
| --- | --- | --- |
| run_hash | VARCHAR(16) PK | Unique identifier for this pipeline execution |
| pdf_filename | VARCHAR(200) | Original PDF filename (normalised) |
| brand | VARCHAR(20) | Brand string provided at initialisation |
| username | TEXT | Engineer who triggered the run |
| created_at | TIMESTAMPTZ | UTC timestamp when the run was initialised |
| status | VARCHAR(10) | Overall run status: running, complete, failed |

### 8.2 stage_events

| Column | Type | Description |
| --- | --- | --- |
| event_id | UUID PK | Auto-generated unique event identifier |
| run_hash | VARCHAR(16) FK | Foreign key to pipeline_runs |
| stage_name | VARCHAR(50) | Name of the pipeline stage |
| status | VARCHAR(10) | started, complete, or failed |
| inputs | JSONB | Array of input file paths |
| outputs | JSONB | Array of output file paths |
| metadata | JSONB | Custom metadata (chunk count, page count, etc.) |
| error_message | VARCHAR(500) | Stack trace or error message if status = failed |
| started_at | TIMESTAMPTZ | UTC timestamp when stage began |
| completed_at | TIMESTAMPTZ | UTC timestamp when stage finished |
| duration_ms | INTEGER | Stage duration in milliseconds |

## 9. Backend Service Architecture

The SDK communicates with a lightweight REST API that acts as the lineage backend. This service is responsible for writing to Cloud SQL and enforcing data validation.

### 9.1 Hosting

| Option | Service | When to Use |
| --- | --- | --- |
| Primary | Cloud Run (serverless) | Default — scales to zero, low cost, no VM management |
| Fallback | Compute Engine VM | If always-on low-latency is required, or Cloud Run cold starts are unacceptable |

### 9.2 REST Endpoints

| SDK Method | HTTP Verb | Endpoint | Description |
| --- | --- | --- | --- |
| add_stage() | POST | /v1/runs/{run_hash}/stages | Record a new stage event |
| update_stage() | PATCH | /v1/stages/{event_id} | Update stage display name or metadata |
| delete_stage() | DELETE | /v1/stages/{event_id} | Delete a stage record |
| get_lineage() | GET | /v1/lineage?pdf=...&run=... | Query lineage records |
| (init) | GET | /v1/registry?username=&brand= | Resolve namespace and API config |

### 9.3 Registry Lookup (Cloud SQL)

On SDK initialisation, the backend performs a registry lookup to resolve the engineer's configuration.

> **Note:** At the moment it's just a username — not coming from any database.

## 10. Non-Functional Requirements

| Requirement | Specification |
| --- | --- |
| Async execution | All SDK network calls run in background threads. A lineage failure must never crash the pipeline. |
| Failure handling | If the backend is unreachable, the SDK logs a local warning and continues. It will retry up to 3 times with exponential backoff. |
| No cloud auth overhead | Zero reliance on service account keyfiles or gcloud CLI in pipeline code. Identity is username + brand only. |
| Input validation | The SDK validates that inputs and outputs are non-empty string lists before making any network call. |
| Latency budget | The add_stage() call must add no more than 200ms to the pipeline stage in the P95 case. |
| Cold start tolerance | Cloud Run cold starts are acceptable given async execution. Engineers will not block on lineage writes. |
| Packaging | The SDK will be distributed as an internal PyPI package installable via `pip install lineage-sdk`. |

## 11. Implementation Plan & Phases

### Phase 1 — Backend Service & Database (Week 1–2)

- Provision Cloud SQL PostgreSQL instance on GCP
- Create pipeline_runs and stage_events tables with indexes on run_hash and pdf_filename
- Build the REST API (Python FastAPI recommended) with all five endpoints
- Deploy to Cloud Run with a Cloud SQL connector
- Write integration tests for each endpoint

### Phase 2 — SDK Core (Week 2–3)

- Implement LineageTracker class with `__init__`, add_stage, update_stage, delete_stage, get_lineage
- Implement hash generation (SHA-256 on filename)
- Implement async background thread for all network calls
- Implement retry logic with exponential backoff (3 retries, max 2s delay)
- Implement input validation with clear error messages

### Phase 4 — Packaging & Internal Release (Week 4)

- Package the SDK for internal PyPI distribution
- Write engineer-facing README with quickstart guide and method reference
- Run end-to-end test across all five PDF pipeline stages
- Onboard one pilot engineering team for feedback

## 12. Example Usage

The following shows how an engineer would instrument the full PDF pipeline:

```python
from lineage_sdk import LineageTracker

tracker = LineageTracker(username="jdoe", brand="still")

# Stage 1: Load PDF
tracker.add_stage("pdf_load",
    inputs=["gs://bucket/raw/still/manual.pdf"],
    outputs=["gs://bucket/loaded/still/manual.pdf"],
    metadata={"page_count": 142, "file_size_mb": 8.4})

# Stage 2: Extract TOC
tracker.add_stage("extract_toc",
    inputs=["gs://bucket/loaded/still/manual.pdf"],
    outputs=["gs://bucket/toc/still/manual_toc.json"],
    metadata={"toc_entries": 34})

# Stage 3: Chunk by TOC
tracker.add_stage("chunk_by_toc",
    inputs=["gs://bucket/toc/still/manual_toc.json"],
    outputs=["gs://bucket/chunks/still/manual_chunk_*.json"],
    metadata={"chunk_count": 34})

# Stage 4: Clean & Taxonomy
tracker.add_stage("clean_taxonomy",
    inputs=["gs://bucket/chunks/still/manual_chunk_*.json"],
    outputs=["gs://bucket/cleaned/still/manual_chunk_*.json"],
    metadata={"records_cleaned": 34, "taxonomy_tags": ["engine", "brakes", "safety"]})

# Stage 5: Upload to RAG DB
tracker.add_stage("upload_rag",
    inputs=["gs://bucket/cleaned/still/manual_chunk_*.json"],
    outputs=["spanner:service-ai.still-manual-graph"],
    metadata={"vectors_written": 34})
```

## 13. Open Questions & Decisions Needed

| # | Question | Owner | Answer |
| --- | --- | --- | --- |
| 1 | Should the SDK support async/await (asyncio) in addition to background threads, for use in async pipeline frameworks? | Platform Team | Open |
| 2 | What is the data retention policy for stage_events? Should old records be archived or deleted after a set period? | Data Owner | No |
| 4 | Will the SDK need to support multiple brands per engineer, or is one brand per username sufficient for v1? | Platform Team | Multiple brands per engineer |
| 5 | Should get_lineage() support pagination for engineers with large numbers of runs? | Platform Team | No |

---

*PDF Lineage Tracker SDK | PRD-LINEAGE-SDK-2026-V1 | Confidential — Internal Use Only*
