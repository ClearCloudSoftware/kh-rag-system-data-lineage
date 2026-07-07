import logging

from kh_data_lineage.tracker import LineageTracker
from kh_data_lineage.query import get_lineage

# Library logger stays silent until the host app configures logging.
logging.getLogger("kh_data_lineage").addHandler(logging.NullHandler())

__all__ = ["LineageTracker", "get_lineage"]
