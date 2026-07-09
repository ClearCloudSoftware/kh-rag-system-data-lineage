#!/usr/bin/env python3
"""Demo: emit a few HeatLog registrations to Marquez.

Every stage event carries a `heatlog` run facet whose two headline fields are:
  * THE WHO               -> `username`      (who performed the stage)
  * THE ONTOLOGICAL INDEX -> `ontologicalId` = make/file_hash/stage

The ontological index is the stable identity that ties every stage of one
artifact together; the who changes per stage (registrar, reviewer, ...).

Run against a running Marquez — e.g. the Foundry infra stack (kh-rag-system-infra):
    .venv/bin/python examples/demo_registrations.py

Override the backend with HEATLOG_MARQUEZ_URL. Then open http://localhost:9003
(the Marquez UI): the namespace is the make, the job is the stage, and the
who + ontological index sit on each run's `heatlog` facet.
"""
import hashlib
import os

from kh_data_lineage import LineageTracker
from kh_data_lineage.events import ontological_id

# Defaults to the Foundry infra stack's Marquez (:9000); override with HEATLOG_MARQUEZ_URL.
URL = os.environ.get("HEATLOG_MARQUEZ_URL", "http://localhost:9000")
BUCKET = "gs://foundry-docs"


def file_hash(make: str, filename: str) -> str:
    """Stand-in for a real content hash — deterministic so reruns stay idempotent."""
    return hashlib.sha256(f"{make}/{filename}".encode()).hexdigest()[:12]


# (who, make, filename, why) — THE WHO leads each row.
REGISTRATIONS = [
    ("jdoe",   "still",     "operator-manual.pdf",  "new manual onboarded"),
    ("asmith", "still",     "parts-catalogue.pdf",  "supplier catalogue added"),
    ("jdoe",   "husqvarna", "chainsaw-535i-xp.pdf", "seasonal model refresh"),
]


def register(who: str, make: str, filename: str, why: str) -> None:
    fh = file_hash(make, filename)
    LineageTracker(
        username=who, make=make, file_hash=fh,
        what="initial registration", why=why,
        pdf_filename=filename, marquez_url=URL,
    ).add_stage(
        "registration",
        inputs=[f"{BUCKET}/loaded/{make}/{filename}"],
        outputs=[f"{BUCKET}/registered/{make}/{filename}"],
        metadata={"pages": 42, "source": "supplier-portal"},
    )
    print(f"  who={who:<9}  ontological_index={ontological_id(make, fh, 'registration')}")


def main() -> None:
    print(f"Emitting {len(REGISTRATIONS)} registrations -> {URL}\n")
    for reg in REGISTRATIONS:
        register(*reg)

    # Same artifact, a later stage, a DIFFERENT who: the ontological index keeps
    # the file_hash; only the stage (and the who) change.
    fh = file_hash("still", "operator-manual.pdf")
    LineageTracker(
        username="breviewer", make="still", file_hash=fh,
        what="editorial review", why="QA pass before publish",
        pdf_filename="operator-manual.pdf", marquez_url=URL,
    ).add_stage(
        "review",
        inputs=[f"{BUCKET}/registered/still/operator-manual.pdf"],
        outputs=[f"{BUCKET}/reviewed/still/operator-manual.pdf"],
        metadata={"verdict": "approved"},
    )
    print(f"  who={'breviewer':<9}  ontological_index={ontological_id('still', fh, 'review')}   (same file, later stage)")

    print("\nDone. Async emits flush on exit. View them at http://localhost:9003 (namespace = make).")


if __name__ == "__main__":
    main()
