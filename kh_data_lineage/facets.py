import attr
from openlineage.client.facet import BaseFacet
from kh_data_lineage.config import HEATLOG_FACET_SCHEMA, HEATLOG_VOID_FACET_SCHEMA


@attr.define
class HeatlogRunFacet(BaseFacet):
    ontologicalId: str
    make: str
    fileHash: str
    filename: str | None
    what: str
    why: str
    username: str
    metadata: dict

    @staticmethod
    def _get_schema() -> str:
        return HEATLOG_FACET_SCHEMA


@attr.define
class HeatlogVoidRunFacet(BaseFacet):
    reason: str
    voidedBy: str

    @staticmethod
    def _get_schema() -> str:
        return HEATLOG_VOID_FACET_SCHEMA
