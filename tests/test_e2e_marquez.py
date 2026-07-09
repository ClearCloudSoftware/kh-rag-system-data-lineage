# tests/test_e2e_marquez.py
import os, uuid, pytest, requests
from kh_data_lineage import LineageTracker

URL = os.environ.get("HEATLOG_MARQUEZ_URL", "http://localhost:5000")

def _up():
    try: return requests.get(f"{URL}/api/v1/namespaces", timeout=2).ok
    except Exception: return False

@pytest.mark.skipif(not _up(), reason="Marquez not running")
def test_stage_lands_in_marquez():
    t = LineageTracker(username="jdoe", make="still", file_hash=uuid.uuid4().hex,
                       what="e2e", why="test", marquez_url=URL)
    t.add_stage("chunking", ["gs://b/in.pdf"], ["gs://b/out.json"], {"chunk_count": 1})
    import time; time.sleep(2)
    jobs = requests.get(f"{URL}/api/v1/namespaces/still/jobs", timeout=5).json()
    assert any(j["name"] == "chunking" for j in jobs.get("jobs", []))
