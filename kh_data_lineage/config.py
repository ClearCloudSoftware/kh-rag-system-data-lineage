# kh_data_lineage/config.py
import os

MARQUEZ_URL: str = os.environ.get("HEATLOG_MARQUEZ_URL", "http://localhost:5000")
PRODUCER: str = "https://bitbucket.org/happyfleet/kh-rag-system-data-lineage"
STAGES: frozenset[str] = frozenset({"registration", "chunking", "review", "graph", "rag"})
PARENT_JOB_NAME: str = "foundry_pipeline"
HEATLOG_FACET_SCHEMA: str = f"{PRODUCER}/schemas/heatlog-run-facet.json"
HEATLOG_VOID_FACET_SCHEMA: str = f"{PRODUCER}/schemas/heatlog-void-run-facet.json"
