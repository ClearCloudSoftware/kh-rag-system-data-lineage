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
                   run_id="a0d1…", pdf_filename="manual.pdf")

t.add_stage("chunking",
    inputs=["gs://bucket/registered/still/manual.pdf"],
    outputs=["gs://bucket/chunks/still/manual_chunk_0001.json"],
    metadata={"chunk_count": 34})
```

Stages: `registration`, `chunking`, `review`, `graph`, `rag`. `add_stage` never blocks or raises into your pipeline.
