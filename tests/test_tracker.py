# tests/test_tracker.py
import pytest
from kh_data_lineage.tracker import LineageTracker

class Recorder:                     # stand-in emitter
    def __init__(self): self.events = []
    def emit(self, e): self.events.append(e)

def _tracker(**kw):
    base = dict(username="jdoe", brand="still", file_hash="h", what="w", why="y")
    t = LineageTracker(**{**base, **kw})
    t._emitter = Recorder()
    return t

def test_missing_what_raises():
    with pytest.raises(ValueError):
        LineageTracker(username="jdoe", brand="still", file_hash="h", what="", why="y")

def test_run_id_minted_when_absent():
    t = _tracker()
    assert t.run_id  # non-empty uuid string

def test_add_stage_emits_one_event():
    t = _tracker()
    t.add_stage("chunking", ["gs://b/in.pdf"], ["gs://b/out.json"], {"chunk_count": 3})
    assert len(t._emitter.events) == 1
    assert t._emitter.events[0].job.name == "chunking"

def test_add_stage_rejects_unknown_stage():
    t = _tracker()
    with pytest.raises(ValueError):
        t.add_stage("bogus", ["a"], ["b"])

def test_add_stage_rejects_empty_inputs():
    t = _tracker()
    with pytest.raises(ValueError):
        t.add_stage("chunking", [], ["b"])

def test_void_emits_abort():
    t = _tracker()
    t.void("junk run")
    assert t._emitter.events[0].eventType.value == "ABORT"
