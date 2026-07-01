from kh_data_lineage.events import ontological_id, split_dataset

def test_ontological_id_lowercases_make():
    assert ontological_id("STILL", "3f9ac7", "chunking") == "still/3f9ac7/chunking"

def test_split_dataset_gcs():
    assert split_dataset("gs://bucket/loaded/still/manual.pdf") == ("gs://bucket", "loaded/still/manual.pdf")

def test_split_dataset_scheme_only():
    assert split_dataset("spanner:service-ai.still-vectors") == ("spanner", "service-ai.still-vectors")

def test_split_dataset_bare_path():
    assert split_dataset("/tmp/x.json") == ("file", "/tmp/x.json")
