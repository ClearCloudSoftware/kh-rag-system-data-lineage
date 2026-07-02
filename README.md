# kh-data-lineage (HeatLog)

Foundry data-lineage SDK. Emits one OpenLineage event per Foundry stage to Marquez.

```bash
pip install kh-data-lineage
export HEATLOG_MARQUEZ_URL=http://localhost:5000
```

```python
from kh_data_lineage import LineageTracker

t = LineageTracker(username="jdoe", brand="still", file_hash="3f9a…c7",
                   what="initial processing", why="new manual onboarded",
                   pdf_filename="manual.pdf")

t.add_stage("chunking",
    inputs=["gs://bucket/registered/still/manual.pdf"],
    outputs=["gs://bucket/chunks/still/manual_chunk_0001.json"],
    metadata={"chunk_count": 34})
```

Stages: `registration`, `chunking`, `review`, `graph`, `rag`. `add_stage` never blocks or raises into your pipeline.

## The heatlog facet: the who & the ontological index

Every event carries a `heatlog` run facet with two identity fields:

- **The who** — `username`: who performed the stage (attribution rides on the run).
- **The ontological index** — `ontologicalId` = `make/file_hash/stage`: the stable identity of one artifact at one stage. The `file_hash` is invariant across a document's whole lifecycle, so the ontological index ties every stage of the same artifact together while the *who* changes per stage (registrar, reviewer, …):

```
still/03db25930a44/registration   ← jdoe registered the manual
still/03db25930a44/review         ← breviewer reviewed the same artifact
```

Query by `file_hash` to reconstruct a document's whole journey; query by `username` to see what a person touched.

## Demo

`examples/demo_registrations.py` emits a few registrations (plus one review of the same artifact by a different who) into Marquez and prints each event's who + ontological index:

```bash
.venv/bin/python examples/demo_registrations.py     # → open http://localhost:9003 (namespace = brand)
```
