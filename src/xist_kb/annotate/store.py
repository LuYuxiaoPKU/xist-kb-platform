"""Human annotations on claims, keyed by content rather than by claim_id.

The reviewer marks a claim correct / wrong / unsure. That judgement has to
survive the claim_id changing, which it will: the id is derived from the claim
text, section and quote, and any cleaner tweak recomputes all 115k of them.
Measured in review round 4: switching the id's inputs changed every id in the
corpus at once.

So the key is a fingerprint of the claim's *content*:

    annotation_key = stable_id("annotation", paper_id, norm(claim), norm(quote))

`claim_id` is stored alongside for convenience, but nothing joins on it.

Writes are append-only in the sense that a re-annotation supersedes the old row
at read time (`latest_annotations`); the file itself is replaced atomically so a
reader never sees a half-written table.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from xist_kb.ingest.migrate_v2 import stable_id

ANNOTATIONS_SCHEMA = pa.schema(
    [
        ("annotation_key", pa.string()),
        ("claim_id", pa.string()),
        ("paper_id", pa.string()),
        ("verdict", pa.string()),  # correct / wrong / unsure
        ("note", pa.string()),
        ("annotator", pa.string()),
        ("created_at", pa.timestamp("us", tz="UTC")),
    ]
)

VERDICTS = frozenset({"correct", "wrong", "unsure"})


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).lower()


def annotation_key(paper_id: str, claim: str, quote: str | None) -> str:
    """Content fingerprint. Stable across any claim_id regeneration."""
    return stable_id("annotation", paper_id, _norm(claim), _norm(quote))


@dataclass(frozen=True)
class Annotation:
    annotation_key: str
    claim_id: str
    paper_id: str
    verdict: str
    note: str
    annotator: str
    created_at: datetime


class AnnotationStore:
    """Read/append annotations in one Parquet file.

    Rewriting the whole file on every append is fine at this scale: an
    annotation is a few hundred bytes and the table is expected to reach
    thousands of rows, not millions.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def read(self) -> list[Annotation]:
        if not self.path.exists():
            return []
        table = pq.read_table(self.path)
        return [Annotation(**row) for row in table.to_pylist()]

    def latest(self) -> dict[str, Annotation]:
        """One annotation per key: the newest by created_at."""
        by_key: dict[str, Annotation] = {}
        for ann in self.read():
            current = by_key.get(ann.annotation_key)
            if current is None or ann.created_at >= current.created_at:
                by_key[ann.annotation_key] = ann
        return by_key

    def add(
        self,
        *,
        claim_id: str,
        paper_id: str,
        claim: str,
        quote: str | None,
        verdict: str,
        note: str = "",
        annotator: str = "",
        created_at: datetime | None = None,
    ) -> Annotation:
        if verdict not in VERDICTS:
            raise ValueError(f"verdict must be one of {sorted(VERDICTS)}, got {verdict!r}")

        ann = Annotation(
            annotation_key=annotation_key(paper_id, claim, quote),
            claim_id=claim_id,
            paper_id=paper_id,
            verdict=verdict,
            note=note,
            annotator=annotator,
            created_at=created_at or datetime.now(UTC),
        )
        rows = [a.__dict__ for a in self.read()]
        rows.append(ann.__dict__)
        self._write(rows)
        return ann

    def _write(self, rows: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pylist(rows, ANNOTATIONS_SCHEMA)
        # atomic replace: a reader either sees the old file or the new one
        tmp = self.path.with_suffix(".parquet.tmp")
        pq.write_table(table, tmp)
        os.replace(tmp, self.path)

    def counts(self) -> dict[str, int]:
        latest = self.latest()
        out: dict[str, int] = dict.fromkeys(sorted(VERDICTS), 0)
        for ann in latest.values():
            out[ann.verdict] = out.get(ann.verdict, 0) + 1
        out["total"] = len(latest)
        return out
