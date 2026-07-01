from kh_data_lineage.events import ontological_id, split_dataset, build_stage_event, build_void_event
from openlineage.client.run import RunState

def test_ontological_id_lowercases_make():
    assert ontological_id("STILL", "3f9ac7", "chunking") == "still/3f9ac7/chunking"

def test_split_dataset_gcs():
    assert split_dataset("gs://bucket/loaded/still/manual.pdf") == ("gs://bucket", "loaded/still/manual.pdf")

def test_split_dataset_scheme_only():
    assert split_dataset("spanner:service-ai.still-vectors") == ("spanner", "service-ai.still-vectors")

def test_split_dataset_bare_path():
    assert split_dataset("/tmp/x.json") == ("file", "/tmp/x.json")

STAGE_RUN = "22222222-2222-2222-2222-222222222222"
PARENT_RUN = "11111111-1111-1111-1111-111111111111"

def _stage_event():
    return build_stage_event(
        make="still", file_hash="h", filename="m.pdf", what="w", why="y", username="jdoe",
        parent_run_id=PARENT_RUN, stage="chunking",
        inputs=["gs://b/registered/still/m.pdf"], outputs=["gs://b/chunks/still/m_0001.json"],
        metadata={"chunk_count": 34}, stage_run_id=STAGE_RUN)

def test_stage_event_shape():
    e = _stage_event()
    assert e.eventType == RunState.COMPLETE
    assert e.job.namespace == "still" and e.job.name == "chunking"
    assert e.run.runId == STAGE_RUN
    assert "parent" in e.run.facets and "heatlog" in e.run.facets
    assert e.run.facets["heatlog"].ontologicalId == "still/h/chunking"
    assert len(e.inputs) == 1 and len(e.outputs) == 1
    assert e.inputs[0].namespace == "gs://b"

def test_void_event_shape():
    e = build_void_event(make="still", parent_run_id=PARENT_RUN, reason="junk", voided_by="jdoe")
    assert e.eventType == RunState.ABORT
    assert e.job.name == "foundry_pipeline"
    assert e.run.runId == PARENT_RUN
    assert e.run.facets["heatlog_void"].reason == "junk"
