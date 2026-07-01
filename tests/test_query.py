import pytest
import kh_data_lineage.query as q

class FakeResp:
    def __init__(self, data): self._data = data
    def raise_for_status(self): pass
    def json(self): return self._data

def test_requires_a_handle():
    with pytest.raises(ValueError):
        q.get_lineage()

def test_dataset_builds_nodeid(monkeypatch):
    seen = {}
    def fake_get(url, params=None, timeout=None):
        seen["url"], seen["params"] = url, params
        return FakeResp({"graph": []})
    monkeypatch.setattr(q.requests, "get", fake_get)
    q.get_lineage(dataset="gs://b/x.json", marquez_url="http://m:5000")
    assert seen["url"] == "http://m:5000/api/v1/lineage"
    assert seen["params"] == {"nodeId": "dataset:gs://b:x.json"}
