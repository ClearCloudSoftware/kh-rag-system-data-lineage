from urllib.parse import urlparse

def ontological_id(make: str, file_hash: str, stage: str) -> str:
    return f"{make.lower()}/{file_hash}/{stage}"

def split_dataset(path: str) -> tuple[str, str]:
    parsed = urlparse(path)
    if parsed.scheme and parsed.netloc:            # gs://bucket/loaded/x.pdf
        return f"{parsed.scheme}://{parsed.netloc}", parsed.path.lstrip("/")
    if parsed.scheme:                              # spanner:svc.tbl / neo4j:still.graph
        return parsed.scheme, parsed.path or parsed.netloc
    return "file", path                            # bare local path
