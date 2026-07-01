from datetime import datetime, timezone
from urllib.parse import urlparse
from openlineage.client.run import RunEvent, RunState, Run, Job, InputDataset, OutputDataset
from openlineage.client.facet import ParentRunFacet
from kh_data_lineage.config import PRODUCER, PARENT_JOB_NAME
from kh_data_lineage.facets import HeatlogRunFacet, HeatlogVoidRunFacet

def ontological_id(make: str, file_hash: str, stage: str) -> str:
    return f"{make.lower()}/{file_hash}/{stage}"

def split_dataset(path: str) -> tuple[str, str]:
    parsed = urlparse(path)
    if parsed.scheme and parsed.netloc:            # gs://bucket/loaded/x.pdf
        return f"{parsed.scheme}://{parsed.netloc}", parsed.path.lstrip("/")
    if parsed.scheme:                              # spanner:svc.tbl / neo4j:still.graph
        return parsed.scheme, parsed.path or parsed.netloc
    return "file", path                            # bare local path

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def build_stage_event(*, make, file_hash, filename, what, why, username,
                      parent_run_id, stage, inputs, outputs, metadata, stage_run_id) -> RunEvent:
    run = Run(runId=stage_run_id, facets={
        "parent": ParentRunFacet.create(runId=parent_run_id, namespace=make, name=PARENT_JOB_NAME),
        "heatlog": HeatlogRunFacet(ontological_id(make, file_hash, stage), make, file_hash,
                                   filename, what, why, username, metadata or {}),
    })
    return RunEvent(
        eventType=RunState.COMPLETE, eventTime=_now(),
        run=run, job=Job(namespace=make, name=stage), producer=PRODUCER,
        inputs=[InputDataset(*split_dataset(p)) for p in inputs],
        outputs=[OutputDataset(*split_dataset(p)) for p in outputs],
    )

def build_void_event(*, make, parent_run_id, reason, voided_by) -> RunEvent:
    run = Run(runId=parent_run_id, facets={"heatlog_void": HeatlogVoidRunFacet(reason, voided_by)})
    return RunEvent(
        eventType=RunState.ABORT, eventTime=_now(),
        run=run, job=Job(namespace=make, name=PARENT_JOB_NAME), producer=PRODUCER,
        inputs=[], outputs=[],
    )
