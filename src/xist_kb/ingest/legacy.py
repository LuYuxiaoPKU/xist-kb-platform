"""Read the V2 knowledge base from disk.

V2's shapes, all of which the migration has to cope with:

* `metadata/papers.csv` — the registry, 10 columns, `year` as text and
  `species` mostly blank.
* `notes/json/*.json` — one annotation per paper, no record of how it was
  produced.
* `notes/claims/*_claims.csv` — flattened claims, one CSV per paper, all
  sharing a header.
* `xist_knowledge.db` — SQLite with the six tables V2 queried.

Nothing here writes; the readers return plain dicts and the caller decides
how to repair and where to publish.
"""

from __future__ import annotations

import csv
import json
import logging
import sqlite3
from collections.abc import Iterator
from pathlib import Path

log = logging.getLogger(__name__)

PAPER_COLUMNS = (
    "paper_id",
    "title",
    "year",
    "journal",
    "doi",
    "pmid",
    "species",
    "taxonomic_group",
    "first_author",
    "status",
)

CLAIM_COLUMNS = (
    "paper_id",
    "claim",
    "topic",
    "evidence",
    "evidence_type",
    "directness",
    "section",
    "paragraph",
    "figure_or_table",
    "species",
    "cell_type",
    "confidence",
    "caveat",
)

SQLITE_TABLES = (
    "papers",
    "claims",
    "regulations",
    "interactors",
    "xci_status",
    "species_xist",
)


class V2Source:
    """A read-only view of a V2 project checkout."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.papers_csv = self.root / "metadata" / "papers.csv"
        self.json_dir = self.root / "notes" / "json"
        self.claims_dir = self.root / "notes" / "claims"
        self.text_dir = self.root / "papers" / "text"
        self.pdf_dir = self.root / "papers" / "pdf"
        self.db_path = self.root / "xist_knowledge.db"

    def check(self) -> list[str]:
        """Return a list of missing pieces; empty means the source is usable."""
        missing = []
        for name, path in (
            ("papers.csv", self.papers_csv),
            ("notes/json", self.json_dir),
            ("notes/claims", self.claims_dir),
            ("xist_knowledge.db", self.db_path),
        ):
            if not path.exists():
                missing.append(name)
        return missing

    # -- registry --------------------------------------------------------

    def iter_papers(self) -> Iterator[dict]:
        with self.papers_csv.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                return
            missing = set(PAPER_COLUMNS) - set(reader.fieldnames)
            if missing:
                raise ValueError(f"papers.csv is missing columns: {sorted(missing)}")
            yield from reader

    # -- annotations -----------------------------------------------------

    def iter_annotations(self) -> Iterator[tuple[str, dict]]:
        """Yield (paper_id, parsed JSON) for every annotation file.

        Files that fail to parse are logged and skipped rather than aborting
        the migration, since one corrupt file should not cost 13k good ones.
        """
        for path in sorted(self.json_dir.glob("*.json")):
            try:
                with path.open(encoding="utf-8") as fh:
                    yield path.stem, json.load(fh)
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("skipping unreadable annotation %s: %s", path.name, exc)

    # -- claims ----------------------------------------------------------

    def iter_claim_rows(self) -> Iterator[dict]:
        """Yield every claim row across all per-paper CSVs."""
        for path in sorted(self.claims_dir.glob("*_claims.csv")):
            try:
                with path.open(encoding="utf-8", newline="") as fh:
                    reader = csv.DictReader(fh)
                    if reader.fieldnames is None:
                        continue
                    if set(reader.fieldnames) != set(CLAIM_COLUMNS):
                        log.warning(
                            "unexpected header in %s: %s", path.name, reader.fieldnames
                        )
                        continue
                    yield from reader
            except OSError as exc:
                log.warning("skipping unreadable claims file %s: %s", path.name, exc)

    # -- sqlite ----------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        # Read-only: a migration must never mutate the source of truth.
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def iter_table(self, table: str) -> Iterator[dict]:
        if table not in SQLITE_TABLES:
            raise ValueError(f"unknown table {table!r}; expected one of {list(SQLITE_TABLES)}")
        with self._connect() as conn:
            for row in conn.execute(f"SELECT * FROM {table}"):  # noqa: S608 - table is validated
                yield dict(row)

    def count_table(self, table: str) -> int:
        if table not in SQLITE_TABLES:
            raise ValueError(f"unknown table {table!r}; expected one of {list(SQLITE_TABLES)}")
        with self._connect() as conn:
            return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608

    # -- corpora ---------------------------------------------------------

    def text_ids(self) -> set[str]:
        return {p.stem for p in self.text_dir.glob("*.txt")}

    def pdf_ids(self) -> set[str]:
        return {p.stem for p in self.pdf_dir.glob("*.pdf")}

    def annotation_ids(self) -> set[str]:
        return {p.stem for p in self.json_dir.glob("*.json")}

    def claim_ids(self) -> set[str]:
        return {p.name.removesuffix("_claims.csv") for p in self.claims_dir.glob("*_claims.csv")}
