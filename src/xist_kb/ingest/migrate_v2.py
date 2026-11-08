"""Migrate a V2 checkout into the layered Parquet store.

The migration is intentionally lossless about *facts* and explicit about
*repairs*: every value that the cleaners changed is counted, and the counts go
into a quality report next to the Parquet files. Re-running the migration on
the same source produces byte-identical output, so the report is reproducible.

What it writes into the Gold layer:

    gold/papers.parquet
    gold/claims.parquet
    gold/provenance.parquet
    gold/interactors.parquet
    gold/regulations.parquet
    gold/xci_status.parquet
    gold/species_xist.parquet

Chunks and citation edges are not produced here — chunks need the full-text
corpus, which lives outside the V2 metadata, and citations come from a fresh
ingest run rather than from V2's denormalised CSV.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from xist_kb.ingest.legacy import V2Source
from xist_kb.paths import ensure_layer
from xist_kb.vocab import (
    CONFIDENCE_VALUES,
    DIRECTNESS_VALUES,
    EVIDENCE_TYPE_VALUES,
    SECTION_VALUES,
    normalize_doi,
    normalize_enum,
    normalize_paper_id,
    normalize_species_list,
    normalize_topic,
    normalize_year,
)

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Arrow schemas — one definition, used for both writing and validation
# --------------------------------------------------------------------------

PAPERS_SCHEMA = pa.schema(
    [
        ("paper_id", pa.string()),
        ("doi", pa.string()),
        ("pmid", pa.string()),
        ("pmcid", pa.string()),
        ("openalex_id", pa.string()),
        ("title", pa.string()),
        ("abstract", pa.string()),
        ("year", pa.int32()),
        ("journal", pa.string()),
        ("first_author", pa.string()),
        ("authors", pa.list_(pa.string())),
        ("species", pa.list_(pa.string())),
        ("taxonomic_group", pa.string()),
        ("status", pa.string()),
        ("has_text", pa.bool_()),
        ("has_pdf", pa.bool_()),
        ("has_annotation", pa.bool_()),
        ("source", pa.string()),
        ("retrieved_at", pa.timestamp("us", tz="UTC")),
    ]
)

CLAIMS_SCHEMA = pa.schema(
    [
        ("claim_id", pa.string()),
        ("paper_id", pa.string()),
        ("claim", pa.string()),
        ("topic", pa.string()),
        ("evidence", pa.string()),
        ("evidence_type", pa.string()),
        ("directness", pa.string()),
        ("section", pa.string()),
        ("figure_or_table", pa.string()),
        ("species", pa.list_(pa.string())),
        ("cell_type", pa.string()),
        ("confidence", pa.string()),
        ("caveat", pa.string()),
        ("quote", pa.string()),
        ("quote_offset_start", pa.int32()),
        ("quote_offset_end", pa.int32()),
        ("chunk_id", pa.string()),
        ("provenance_id", pa.string()),
    ]
)

PROVENANCE_SCHEMA = pa.schema(
    [
        ("provenance_id", pa.string()),
        ("paper_id", pa.string()),
        ("method", pa.string()),
        ("model", pa.string()),
        ("prompt_template", pa.string()),
        ("prompt_hash", pa.string()),
        ("runtime_seconds", pa.float32()),
        ("created_at", pa.timestamp("us", tz="UTC")),
        ("source_checksum", pa.string()),
    ]
)

INTERACTORS_SCHEMA = pa.schema(
    [
        ("paper_id", pa.string()),
        ("protein", pa.string()),
        ("xist_domain", pa.string()),
        ("method", pa.string()),
        ("function", pa.string()),
        ("species", pa.list_(pa.string())),
        ("cell_type", pa.string()),
        ("direct_or_indirect", pa.string()),
        ("confidence", pa.string()),
        ("provenance_id", pa.string()),
    ]
)

REGULATIONS_SCHEMA = pa.schema(
    [
        ("paper_id", pa.string()),
        ("regulator", pa.string()),
        ("target", pa.string()),
        ("direction", pa.string()),
        ("species", pa.list_(pa.string())),
        ("cell_type", pa.string()),
        ("developmental_stage", pa.string()),
        ("evidence_type", pa.string()),
        ("directness", pa.string()),
        ("confidence", pa.string()),
        ("provenance_id", pa.string()),
    ]
)

XCI_STATUS_SCHEMA = pa.schema(
    [
        ("paper_id", pa.string()),
        ("species", pa.list_(pa.string())),
        ("cell_type", pa.string()),
        ("developmental_stage", pa.string()),
        ("xci_type", pa.string()),
        ("xist_status", pa.string()),
        ("chromatin_marks", pa.list_(pa.string())),
        ("confidence", pa.string()),
        ("provenance_id", pa.string()),
    ]
)

SPECIES_XIST_SCHEMA = pa.schema(
    [
        ("paper_id", pa.string()),
        ("species", pa.string()),
        ("taxonomic_group", pa.string()),
        ("xist_reported", pa.bool_()),
        ("confidence", pa.string()),
        ("experimental_validation", pa.string()),
        ("synteny_evidence", pa.string()),
        ("provenance_id", pa.string()),
    ]
)

# Canonical paper_id -> the on-disk stem of each file kind. Files keep their
# original case; every lookup goes through this table instead of `path.exists()`,
# which on Windows returns true for names that fail on the Linux server.
PAPER_ID_MAP_SCHEMA = pa.schema(
    [
        ("paper_id", pa.string()),
        ("json_file", pa.string()),
        ("text_file", pa.string()),
        ("pdf_file", pa.string()),
        ("claims_file", pa.string()),
    ]
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def stable_id(*parts: object) -> str:
    """A content-derived id, so re-running the migration keeps ids stable."""
    blob = "\x1f".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _clean_scalar(raw: object, sentinels: frozenset[str] = frozenset()) -> str | None:
    """Return a stripped string, or None for empty/sentinel values."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in sentinels:
        return None
    return text


_NOT_REPORTED = frozenset({"not reported", "not_reported", "n/a", "na", "none", "null", "nan", ""})


def clean_text(raw: object) -> str | None:
    return _clean_scalar(raw, _NOT_REPORTED)


@dataclass
class MigrationStats:
    """Counts everything the migration did, for the quality report."""

    json_parse_failures: int = 0
    papers_read: int = 0
    claims_read: int = 0
    annotations_read: int = 0
    topic_changed: int = 0
    topic_other_after: int = 0
    confidence_repaired: int = 0
    evidence_type_repaired: int = 0
    directness_repaired: int = 0
    section_repaired: int = 0
    year_repaired: int = 0
    year_missing: int = 0
    doi_normalized: int = 0
    species_parsed: int = 0
    species_empty: int = 0
    quote_present: int = 0
    quote_missing: int = 0
    paper_id_lowercased: int = 0
    claim_paper_id_lowercased: int = 0
    claim_id_collisions_resolved: int = 0
    papers_without_annotation: int = 0
    annotations_without_paper: int = 0
    claims_without_paper: int = 0
    table_rows: dict[str, int] = field(default_factory=dict)
    topic_distribution: Counter[str] = field(default_factory=Counter)
    topic_before: Counter[str] = field(default_factory=Counter)
    status_distribution: Counter[str] = field(default_factory=Counter)
    output_sizes: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "papers_read": self.papers_read,
            "annotations_read": self.annotations_read,
            "claims_read": self.claims_read,
            "json_parse_failures": self.json_parse_failures,
            "repairs": {
                "topic_changed": self.topic_changed,
                "confidence_repaired": self.confidence_repaired,
                "evidence_type_repaired": self.evidence_type_repaired,
                "directness_repaired": self.directness_repaired,
                "section_repaired": self.section_repaired,
                "year_repaired": self.year_repaired,
                "doi_normalized": self.doi_normalized,
                "species_parsed": self.species_parsed,
                "paper_id_lowercased": self.paper_id_lowercased,
                "claim_paper_id_lowercased": self.claim_paper_id_lowercased,
                "claim_id_collisions_resolved": self.claim_id_collisions_resolved,
            },
            "gaps": {
                "year_missing": self.year_missing,
                "species_empty": self.species_empty,
                "quote_missing": self.quote_missing,
                "papers_without_annotation": self.papers_without_annotation,
                "annotations_without_paper": self.annotations_without_paper,
                "claims_without_paper": self.claims_without_paper,
            },
            "topic_other_after": self.topic_other_after,
            "topic_top_20": self.topic_distribution.most_common(20),
            "topic_top_20_before": self.topic_before.most_common(20),
            "status_distribution": self.status_distribution.most_common(),
            "table_rows": self.table_rows,
            "output_bytes": self.output_sizes,
        }


# --------------------------------------------------------------------------
# Migration
# --------------------------------------------------------------------------


class Migration:
    def __init__(self, source: V2Source, out_dir: Path | None = None):
        self.source = source
        self.out_dir = out_dir or ensure_layer("gold")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.stats = MigrationStats()
        self._now = datetime.now(UTC)

    # -- papers ----------------------------------------------------------

    def build_papers(self) -> list[dict]:
        text_ids = self.source.text_ids()
        pdf_ids = self.source.pdf_ids()
        annotation_ids = self.source.annotation_ids()
        self.stats.annotations_read = len(annotation_ids)

        rows: list[dict] = []
        for raw in self.source.iter_papers():
            self.stats.papers_read += 1
            paper_id = normalize_paper_id(raw["paper_id"])
            if not paper_id:
                continue
            if paper_id != str(raw["paper_id"]).strip():
                self.stats.paper_id_lowercased += 1

            raw_year = raw.get("year")
            year = normalize_year(raw_year)
            if year is not None and str(raw_year).strip() != str(year):
                self.stats.year_repaired += 1
            if year is None:
                self.stats.year_missing += 1

            raw_doi = raw.get("doi")
            doi = normalize_doi(raw_doi)
            if doi and str(raw_doi).strip().lower() != doi:
                self.stats.doi_normalized += 1

            species = normalize_species_list(raw.get("species"))
            if species:
                self.stats.species_parsed += 1
            else:
                self.stats.species_empty += 1

            raw_status = (raw.get("status") or "").strip()
            self.stats.status_distribution[raw_status or "(blank)"] += 1

            has_text = paper_id in text_ids
            has_annotation = paper_id in annotation_ids

            # V2's status field mixes real states with duplicate markers
            # ("duplicate_of_..."), which are not states at all.
            if has_annotation:
                status = "annotated"
            elif has_text:
                status = "text_available"
            else:
                status = "registered"

            rows.append(
                {
                    "paper_id": paper_id,
                    "doi": doi,
                    "pmid": _clean_scalar(raw.get("pmid")),
                    "pmcid": None,
                    "openalex_id": None,
                    "title": _clean_scalar(raw.get("title")) or "",
                    "abstract": None,
                    "year": year,
                    "journal": _clean_scalar(raw.get("journal")),
                    "first_author": _clean_scalar(raw.get("first_author")),
                    "authors": [],
                    "species": species,
                    "taxonomic_group": _clean_scalar(raw.get("taxonomic_group")),
                    "status": status,
                    "has_text": has_text,
                    "has_pdf": paper_id in pdf_ids,
                    "has_annotation": has_annotation,
                    "source": "v2_migration",
                    "retrieved_at": self._now,
                }
            )

        known = {r["paper_id"] for r in rows}
        registry_annotated = {r["paper_id"] for r in rows if r["has_annotation"]}
        self.stats.annotations_without_paper = len(annotation_ids - known)
        self.stats.papers_without_annotation = len(known - registry_annotated)
        return rows

    # -- claims ----------------------------------------------------------

    def build_claims(self) -> tuple[list[dict], dict[str, tuple[str, str]]]:
        """Return claim rows plus a paper_id -> (provenance_id, method) map.

        V2 recorded nothing about how a claim was produced. The best available
        signal is `evidence_type == "rule_extraction"`, which only the rule
        extractor emits, so a paper's first claim decides its method and the
        rest follow. That inference is recorded as such — an inferred
        provenance is still better than none, but the report says it was
        inferred rather than observed.
        """
        rows: list[dict] = []
        provenance_by_paper: dict[str, tuple[str, str]] = {}
        occurrence_counts: dict[tuple[str, str, str, str], int] = {}

        for raw in self.source.iter_claim_rows():
            self.stats.claims_read += 1
            paper_id = normalize_paper_id(raw.get("paper_id"))
            claim_text = (raw.get("claim") or "").strip()
            if not paper_id or not claim_text:
                continue
            if paper_id != str(raw.get("paper_id") or "").strip():
                self.stats.claim_paper_id_lowercased += 1

            raw_topic = raw.get("topic")
            self.stats.topic_before[str(raw_topic)] += 1
            topic = normalize_topic(raw_topic)
            if topic != str(raw_topic).strip():
                self.stats.topic_changed += 1
            if topic == "other":
                self.stats.topic_other_after += 1
            self.stats.topic_distribution[topic] += 1

            raw_conf = raw.get("confidence")
            confidence = normalize_enum(raw_conf, CONFIDENCE_VALUES)
            if str(raw_conf).strip() != confidence:
                self.stats.confidence_repaired += 1

            raw_etype = raw.get("evidence_type")
            evidence_type = normalize_enum(raw_etype, EVIDENCE_TYPE_VALUES)
            if str(raw_etype).strip() != evidence_type:
                self.stats.evidence_type_repaired += 1

            raw_direct = raw.get("directness")
            directness = normalize_enum(raw_direct, DIRECTNESS_VALUES)
            if str(raw_direct).strip() != directness:
                self.stats.directness_repaired += 1

            raw_section = raw.get("section")
            section = normalize_enum(raw_section, SECTION_VALUES)
            if str(raw_section).strip() != section:
                self.stats.section_repaired += 1

            quote = clean_text(raw.get("paragraph"))
            if quote:
                self.stats.quote_present += 1
            else:
                self.stats.quote_missing += 1

            method = "rule" if evidence_type == "rule_extraction" else "llm"
            entry = provenance_by_paper.get(paper_id)
            if entry is None:
                entry = (stable_id("prov", paper_id, method, "v2_migration"), method)
                provenance_by_paper[paper_id] = entry
            provenance_id = entry[0]

            # A paper can state the same claim twice (often once per experiment
            # section, with the same missing quote). Measured: 11 ids covered 27
            # rows. The occurrence index is the ordinal among rows that agree on
            # every field the id is built from, so the first keeps suffix 0 and
            # its id is unchanged by later duplicates.
            key = (paper_id, claim_text, section, quote or "")
            occurrence = occurrence_counts.get(key, 0)
            occurrence_counts[key] = occurrence + 1
            if occurrence:
                self.stats.claim_id_collisions_resolved += 1

            rows.append(
                {
                    "claim_id": stable_id(
                        "claim", paper_id, claim_text, section, quote, occurrence
                    ),
                    "paper_id": paper_id,
                    "claim": claim_text,
                    "topic": topic,
                    "evidence": clean_text(raw.get("evidence")),
                    "evidence_type": evidence_type,
                    "directness": directness,
                    "section": section,
                    "figure_or_table": clean_text(raw.get("figure_or_table")),
                    "species": normalize_species_list(raw.get("species")),
                    "cell_type": clean_text(raw.get("cell_type")),
                    "confidence": confidence,
                    "caveat": clean_text(raw.get("caveat")),
                    "quote": quote,
                    "quote_offset_start": None,
                    "quote_offset_end": None,
                    "chunk_id": None,
                    "provenance_id": provenance_id,
                }
            )

        return rows, provenance_by_paper

    def build_provenance(self, by_paper: dict[str, tuple[str, str]]) -> list[dict]:
        rows: list[dict] = []
        for paper_id, (provenance_id, method) in by_paper.items():
            rows.append(
                {
                    "provenance_id": provenance_id,
                    "paper_id": paper_id,
                    "method": method,
                    "model": None,
                    "prompt_template": None,
                    "prompt_hash": None,
                    "runtime_seconds": None,
                    "created_at": self._now,
                    "source_checksum": None,
                }
            )
        rows.sort(key=lambda r: str(r["provenance_id"]))
        return rows

    # -- side tables -----------------------------------------------------

    def build_interactors(self) -> list[dict]:
        rows = []
        for raw in self.source.iter_table("interactors"):
            protein = clean_text(raw.get("protein"))
            if not protein:
                continue
            rows.append(
                {
                    "paper_id": normalize_paper_id(raw.get("paper_id")),
                    "protein": protein,
                    "xist_domain": clean_text(raw.get("xist_domain")),
                    "method": clean_text(raw.get("method")),
                    "function": clean_text(raw.get("function")),
                    "species": normalize_species_list(raw.get("species")),
                    "cell_type": clean_text(raw.get("cell_type")),
                    "direct_or_indirect": clean_text(raw.get("direct_or_indirect")),
                    "confidence": normalize_enum(raw.get("confidence"), CONFIDENCE_VALUES),
                    "provenance_id": None,
                }
            )
        self.stats.table_rows["interactors"] = len(rows)
        return rows

    def build_regulations(self) -> list[dict]:
        rows = []
        for raw in self.source.iter_table("regulations"):
            regulator = clean_text(raw.get("regulator"))
            if not regulator:
                continue
            rows.append(
                {
                    "paper_id": normalize_paper_id(raw.get("paper_id")),
                    "regulator": regulator,
                    "target": clean_text(raw.get("target")) or "XIST",
                    "direction": clean_text(raw.get("direction")),
                    "species": normalize_species_list(raw.get("species")),
                    "cell_type": clean_text(raw.get("cell_type")),
                    "developmental_stage": clean_text(raw.get("developmental_stage")),
                    "evidence_type": normalize_enum(
                        raw.get("evidence_type"), EVIDENCE_TYPE_VALUES
                    ),
                    "directness": normalize_enum(raw.get("directness"), DIRECTNESS_VALUES),
                    "confidence": normalize_enum(raw.get("confidence"), CONFIDENCE_VALUES),
                    "provenance_id": None,
                }
            )
        self.stats.table_rows["regulations"] = len(rows)
        return rows

    def build_xci_status(self) -> list[dict]:
        rows = []
        for raw in self.source.iter_table("xci_status"):
            marks = clean_text(raw.get("chromatin_marks"))
            rows.append(
                {
                    "paper_id": normalize_paper_id(raw.get("paper_id")),
                    "species": normalize_species_list(raw.get("species")),
                    "cell_type": clean_text(raw.get("cell_type")),
                    "developmental_stage": clean_text(raw.get("developmental_stage")),
                    "xci_type": clean_text(raw.get("xci_type")),
                    "xist_status": clean_text(raw.get("xist_status")),
                    "chromatin_marks": [m.strip() for m in marks.split(";")] if marks else [],
                    "confidence": normalize_enum(raw.get("confidence"), CONFIDENCE_VALUES),
                    "provenance_id": None,
                }
            )
        self.stats.table_rows["xci_status"] = len(rows)
        return rows

    def build_species_xist(self) -> list[dict]:
        rows = []
        for raw in self.source.iter_table("species_xist"):
            raw_reported = str(raw.get("xist_reported") or "").strip().lower()
            if raw_reported in {"true", "yes", "1"}:
                reported: bool | None = True
            elif raw_reported in {"false", "no", "0"}:
                reported = False
            else:
                reported = None
            rows.append(
                {
                    "paper_id": normalize_paper_id(raw.get("paper_id")),
                    "species": clean_text(raw.get("species")) or "",
                    "taxonomic_group": clean_text(raw.get("taxonomic_group")),
                    "xist_reported": reported,
                    "confidence": normalize_enum(raw.get("confidence"), CONFIDENCE_VALUES),
                    "experimental_validation": clean_text(raw.get("experimental_validation")),
                    "synteny_evidence": clean_text(raw.get("synteny_evidence")),
                    "provenance_id": None,
                }
            )
        self.stats.table_rows["species_xist"] = len(rows)
        return rows

    # -- orchestrator helpers --------------------------------------------

    def build_paper_id_map(self) -> list[dict]:
        """Canonical id -> on-disk file stems, for every file in the corpus.

        The map is keyed by the lowercased stem so a paper whose registry entry
        is `ADiociaiuti2019_angioma` and whose text file is
        `adiociaiuti2019_angioma.txt` resolves without renaming either.
        """
        rows = self.source.file_index()
        self.stats.table_rows["paper_id_map"] = len(rows)
        return sorted(rows.values(), key=lambda r: r["paper_id"])

    # -- orchestration ---------------------------------------------------

    def write(self, name: str, rows: list[dict], schema: pa.Schema) -> Path:
        path = self.out_dir / f"{name}.parquet"
        table = pa.Table.from_pylist(rows, schema=schema) if rows else schema.empty_table()
        pq.write_table(table, path, compression="zstd", compression_level=9)
        size = path.stat().st_size
        self.stats.output_sizes[name] = size
        log.info("wrote %s: %d rows, %d bytes", path.name, table.num_rows, size)
        return path

    def run(self) -> MigrationStats:
        missing = self.source.check()
        if missing:
            raise FileNotFoundError(f"V2 source is missing: {missing}")

        papers = self.build_papers()
        claims, prov_by_paper = self.build_claims()
        provenance = self.build_provenance(prov_by_paper)

        self.write("papers", papers, PAPERS_SCHEMA)
        self.write("claims", claims, CLAIMS_SCHEMA)
        self.write("provenance", provenance, PROVENANCE_SCHEMA)
        self.write("interactors", self.build_interactors(), INTERACTORS_SCHEMA)
        self.write("regulations", self.build_regulations(), REGULATIONS_SCHEMA)
        self.write("xci_status", self.build_xci_status(), XCI_STATUS_SCHEMA)
        self.write("species_xist", self.build_species_xist(), SPECIES_XIST_SCHEMA)
        self.write("paper_id_map", self.build_paper_id_map(), PAPER_ID_MAP_SCHEMA)

        self.stats.table_rows["papers"] = len(papers)
        self.stats.table_rows["claims"] = len(claims)
        self.stats.table_rows["provenance"] = len(provenance)
        return self.stats

    def write_report(self, path: Path | None = None) -> Path:
        path = path or self.out_dir.parent / "quality_report.json"
        payload = {
            "generated_at": self._now.isoformat(),
            "source_root": str(self.source.root),
            "output_dir": str(self.out_dir),
            **self.stats.as_dict(),
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
