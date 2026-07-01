import attr
from kh_data_lineage.facets import HeatlogRunFacet, HeatlogVoidRunFacet


def test_run_facet_holds_fields():
    f = HeatlogRunFacet("still/h/chunking", "still", "h", "m.pdf", "w", "y", "jdoe", {"chunk_count": 34})
    assert f.ontologicalId == "still/h/chunking"
    assert f.metadata == {"chunk_count": 34}


def test_run_facet_serializes_with_producer_and_schema():
    f = HeatlogRunFacet("still/h/chunking", "still", "h", None, "w", "y", "jdoe", {})
    d = attr.asdict(f)
    assert d["_producer"] and d["_schemaURL"]


def test_void_facet_fields():
    v = HeatlogVoidRunFacet("test run", "jdoe")
    assert (v.reason, v.voidedBy) == ("test run", "jdoe")
