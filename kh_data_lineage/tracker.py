# kh_data_lineage/tracker.py
import uuid
from kh_data_lineage.config import STAGES, MARQUEZ_URL
from kh_data_lineage.emit import AsyncEmitter, _build_client
from kh_data_lineage.events import build_stage_event, build_void_event

def _require(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value

class LineageTracker:
    def __init__(self, username, brand, file_hash, what, why, *,
                 run_id=None, pdf_filename=None, marquez_url=MARQUEZ_URL):
        _require(username, "username"); _require(brand, "brand")
        _require(file_hash, "file_hash"); _require(what, "what"); _require(why, "why")
        self.username, self.file_hash = username, file_hash
        self.make = brand.strip().lower()
        self.what, self.why, self.filename = what, why, pdf_filename
        self.run_id = run_id or str(uuid.uuid4())
        self._emitter = AsyncEmitter(_build_client(marquez_url))

    def add_stage(self, stage_name, inputs, outputs, metadata=None) -> None:
        if stage_name not in STAGES:
            raise ValueError(f"unknown stage {stage_name!r}; expected one of {sorted(STAGES)}")
        if not inputs or not outputs:
            raise ValueError("inputs and outputs must be non-empty lists")
        event = build_stage_event(
            make=self.make, file_hash=self.file_hash, filename=self.filename,
            what=self.what, why=self.why, username=self.username,
            parent_run_id=self.run_id, stage=stage_name,
            inputs=list(inputs), outputs=list(outputs), metadata=metadata,
            stage_run_id=str(uuid.uuid4()))
        self._emitter.emit(event)

    def void(self, reason) -> None:
        _require(reason, "reason")
        self._emitter.emit(build_void_event(
            make=self.make, parent_run_id=self.run_id, reason=reason, voided_by=self.username))

    @classmethod
    def void_run(cls, run_id, reason, username, brand, *, marquez_url=MARQUEZ_URL) -> None:
        _require(reason, "reason")
        AsyncEmitter(_build_client(marquez_url)).emit(build_void_event(
            make=brand.strip().lower(), parent_run_id=run_id, reason=reason, voided_by=username))
