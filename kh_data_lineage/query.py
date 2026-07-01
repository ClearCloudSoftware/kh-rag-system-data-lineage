import requests
from urllib.parse import quote
from kh_data_lineage.config import MARQUEZ_URL
from kh_data_lineage.events import split_dataset

def get_lineage(*, dataset=None, run_id=None, brand=None,
                include_voided=False, marquez_url=MARQUEZ_URL) -> dict:
    if dataset:
        ns, name = split_dataset(dataset)
        r = requests.get(f"{marquez_url}/api/v1/lineage",
                         params={"nodeId": f"dataset:{ns}:{name}"}, timeout=10)
    elif run_id:
        r = requests.get(f"{marquez_url}/api/v1/jobs/runs/{quote(run_id, safe='')}", timeout=10)
    elif brand:
        r = requests.get(f"{marquez_url}/api/v1/namespaces/{quote(brand, safe='')}/jobs", timeout=10)
    else:
        raise ValueError("one of dataset / run_id / brand is required")
    r.raise_for_status()
    data = r.json()
    return data if include_voided else _drop_voided(data)

def _drop_voided(data: dict) -> dict:
    # PoC best-effort: drop graph nodes whose run facets carry heatlog_void.
    nodes = data.get("graph")
    if not isinstance(nodes, list):
        return data
    kept = [n for n in nodes if "heatlog_void" not in _facets_of(n)]
    return {**data, "graph": kept}

def _facets_of(node: dict) -> dict:
    return (((node or {}).get("data") or {}).get("run") or {}).get("facets") or {}
