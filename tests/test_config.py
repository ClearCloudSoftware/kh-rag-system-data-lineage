# tests/test_config.py
from kh_data_lineage import config

def test_stage_vocabulary_is_exact():
    assert config.STAGES == {"registration", "chunking", "review", "graph", "rag"}

def test_marquez_url_env_override(monkeypatch):
    monkeypatch.setenv("HEATLOG_MARQUEZ_URL", "http://marquez.internal:5000")
    import importlib; importlib.reload(config)
    assert config.MARQUEZ_URL == "http://marquez.internal:5000"
