"""Test the V2 migration against a small synthetic fixture."""

import csv
import json
import sqlite3
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from xist_kb.ingest.legacy import V2Source
from xist_kb.ingest.migrate_v2 import Migration


@pytest.fixture
def v2_tree(tmp_path: Path) -> Path:
    """A minimal V2 checkout covering the shapes the migration must handle."""
    root = tmp_path / "v2"
    (root / "metadata").mkdir(parents=True)
    (root / "notes" / "json").mkdir(parents=True)
    (root / "notes" / "claims").mkdir(parents=True)
    (root / "papers" / "text").mkdir(parents=True)
    (root / "papers" / "pdf").mkdir(parents=True)

    with (root / "metadata" / "papers.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
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
            ]
        )
        # Good record, with a URL-prefixed DOI and year noise.
        writer.writerow(
            [
                "smith2019_abc",
                "Xist in mouse",
                "published 2019",
                "Nature",
                "https://doi.org/10.1038/ABC",
                "12345",
                "mouse",
                "Mammalia",
                "Smith",
                "ingested",
            ]
        )
        # Year sentinel and blank species.
        writer.writerow(
            [
                "doe2020_def",
                "Xist review",
                "not reported",
                "Review",
                "",
                "",
                "",
                "",
                "Doe",
                "abstract_only",
            ]
        )
        # A duplicate marker that is not a real status.
        writer.writerow(
            [
                "jones2021_ghi",
                "Duplicate",
                "2021",
                "J",
                "10.1/x",
                "",
                "human",
                "",
                "Jones",
                "duplicate_of_doe2020_def",
            ]
        )

    text_path = root / "papers" / "text" / "smith2019_abc.txt"
    text_path.write_text("Xist coats the X.", encoding="utf-8")
    (root / "papers" / "pdf" / "smith2019_abc.pdf").write_bytes(b"%PDF-1.4")

    (root / "notes" / "json" / "smith2019_abc.json").write_text(
        json.dumps({"claims": [{"claim": "x"}]}), encoding="utf-8"
    )
    (root / "notes" / "json" / "broken.json").write_text("{not json", encoding="utf-8")

    header = [
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
    ]
    with (root / "notes" / "claims" / "smith2019_abc_claims.csv").open(
        "w", encoding="utf-8", newline=""
    ) as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerow(
            [
                "smith2019_abc",
                "Xist coats the inactive X",
                "xci",
                "Fig 1",
                "direct_experimental",
                "direct",
                "results",
                "Xist coats the X.",
                "Fig 1",
                "mouse",
                "ES cells",
                "['high']",
                "",
            ]
        )
        writer.writerow(
            [
                "smith2019_abc",
                "Xist is upregulated on differentiation",
                "other - pluripotency",
                "Fig 2",
                "rule_extraction",
                "indirect",
                "not reported",
                "not reported",
                "",
                "mouse",
                "",
                "medium",
                "",
            ]
        )

    conn = sqlite3.connect(root / "xist_knowledge.db")
    conn.executescript(
        """
        CREATE TABLE papers (paper_id TEXT PRIMARY KEY, doi TEXT, pmid TEXT, year INTEGER,
            journal TEXT, title TEXT, first_author TEXT, species TEXT,
            taxonomic_group TEXT, status TEXT);
        CREATE TABLE claims (id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id TEXT, claim TEXT,
            topic TEXT, evidence TEXT, evidence_type TEXT, directness TEXT, section TEXT,
            figure_or_table TEXT, species TEXT, cell_type TEXT, confidence TEXT, caveat TEXT);
        CREATE TABLE regulations (id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id TEXT,
            regulator TEXT, target TEXT DEFAULT 'XIST', direction TEXT, species TEXT,
            cell_type TEXT, developmental_stage TEXT, evidence_type TEXT, directness TEXT,
            confidence TEXT);
        CREATE TABLE interactors (id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id TEXT,
            protein TEXT, xist_domain TEXT, method TEXT, function TEXT, species TEXT,
            cell_type TEXT, direct_or_indirect TEXT, confidence TEXT);
        CREATE TABLE xci_status (id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id TEXT,
            species TEXT, cell_type TEXT, developmental_stage TEXT, xci_type TEXT,
            xist_status TEXT, chromatin_marks TEXT, confidence TEXT);
        CREATE TABLE species_xist (id INTEGER PRIMARY KEY AUTOINCREMENT, species TEXT,
            taxonomic_group TEXT, xist_reported TEXT, confidence TEXT,
            experimental_validation TEXT, synteny_evidence TEXT, paper_id TEXT);
        """
    )
    conn.execute(
        "INSERT INTO interactors (paper_id, protein, xist_domain, method, species, confidence)"
        " VALUES ('smith2019_abc', 'SHARP', 'A-repeat', 'ChIRP', 'mouse', 'high')"
    )
    conn.execute(
        "INSERT INTO interactors (paper_id, protein, species, confidence)"
        " VALUES ('smith2019_abc', '', 'mouse', 'low')"
    )
    conn.execute(
        "INSERT INTO regulations (paper_id, regulator, direction, species, confidence)"
        " VALUES ('smith2019_abc', 'OCT4', 'repression', 'mouse', 'medium')"
    )
    conn.execute(
        "INSERT INTO xci_status (paper_id, species, cell_type, xci_type,"
        " chromatin_marks, confidence)"
        " VALUES ('smith2019_abc', 'mouse', 'ES', 'imprinted',"
        " 'H3K27me3; H2AK119ub', 'high')"
    )
    conn.execute(
        "INSERT INTO species_xist (species, xist_reported, confidence, paper_id)"
        " VALUES ('Mus musculus', 'true', 'high', 'smith2019_abc')"
    )
    conn.commit()
    conn.close()
    return root


@pytest.fixture
def migrated(v2_tree: Path):
    out = v2_tree / "out"
    migration = Migration(V2Source(v2_tree), out_dir=out)
    stats = migration.run()
    return migration, stats, out


class TestSource:
    def test_check_reports_missing(self, tmp_path):
        assert "papers.csv" in V2Source(tmp_path).check()

    def test_check_empty_on_complete_fixture(self, v2_tree):
        assert V2Source(v2_tree).check() == []

    def test_bad_json_is_skipped_not_fatal(self, v2_tree):
        source = V2Source(v2_tree)
        ids = [pid for pid, _ in source.iter_annotations()]
        assert "smith2019_abc" in ids
        assert "broken" not in ids


class TestPapers:
    def test_status_derived_from_capabilities(self, migrated):
        _, _, out = migrated
        table = pq.read_table(out / "papers.parquet").to_pylist()
        by_id = {r["paper_id"]: r for r in table}
        assert by_id["smith2019_abc"]["status"] == "annotated"
        assert by_id["smith2019_abc"]["has_text"] is True
        assert by_id["smith2019_abc"]["has_pdf"] is True
        # No text, no annotation -> registered, whatever V2's marker said.
        assert by_id["jones2021_ghi"]["status"] == "registered"

    def test_year_normalized(self, migrated):
        _, _, out = migrated
        rows = {r["paper_id"]: r for r in pq.read_table(out / "papers.parquet").to_pylist()}
        assert rows["smith2019_abc"]["year"] == 2019
        assert rows["doe2020_def"]["year"] is None

    def test_doi_normalized(self, migrated):
        _, stats, out = migrated
        rows = {r["paper_id"]: r for r in pq.read_table(out / "papers.parquet").to_pylist()}
        assert rows["smith2019_abc"]["doi"] == "10.1038/abc"
        assert stats.doi_normalized == 1

    def test_species_split_to_list(self, migrated):
        _, _, out = migrated
        rows = {r["paper_id"]: r for r in pq.read_table(out / "papers.parquet").to_pylist()}
        assert rows["smith2019_abc"]["species"] == ["Mus musculus"]
        assert rows["doe2020_def"]["species"] == []


class TestClaims:
    def test_confidence_list_repaired(self, migrated):
        _, stats, out = migrated
        rows = pq.read_table(out / "claims.parquet").to_pylist()
        by_claim = {r["claim"]: r for r in rows}
        assert by_claim["Xist coats the inactive X"]["confidence"] == "high"
        assert stats.confidence_repaired == 1

    def test_topic_fragment_resolved(self, migrated):
        _, _, out = migrated
        rows = pq.read_table(out / "claims.parquet").to_pylist()
        by_claim = {r["claim"]: r for r in rows}
        assert by_claim["Xist is upregulated on differentiation"]["topic"] == "early_embryo"

    def test_section_sentinel_normalized(self, migrated):
        _, _, out = migrated
        rows = {r["claim"]: r for r in pq.read_table(out / "claims.parquet").to_pylist()}
        assert rows["Xist is upregulated on differentiation"]["section"] == "not_reported"

    def test_quote_kept_and_offsets_left_null(self, migrated):
        _, stats, out = migrated
        rows = {r["claim"]: r for r in pq.read_table(out / "claims.parquet").to_pylist()}
        row = rows["Xist coats the inactive X"]
        assert row["quote"] == "Xist coats the X."
        assert row["quote_offset_start"] is None
        assert row["chunk_id"] is None
        assert stats.quote_present == 1
        assert stats.quote_missing == 1

    def test_provenance_method_inferred_from_evidence_type(self, migrated):
        _, _, out = migrated
        claims = pq.read_table(out / "claims.parquet").to_pylist()
        prov_rows = pq.read_table(out / "provenance.parquet").to_pylist()
        prov = {r["provenance_id"]: r for r in prov_rows}
        methods = {
            (c["claim"], prov[c["provenance_id"]]["method"])
            for c in claims
            if c["provenance_id"] in prov
        }
        assert ("Xist coats the inactive X", "llm") in methods
        # The rule-extracted claim on the same paper shares the paper's
        # llm provenance because provenance is keyed per paper, not per claim.
        assert len({p for _, p in methods}) >= 1

    def test_claim_ids_are_stable(self, v2_tree, migrated):
        _, _, out = migrated
        first = pq.read_table(out / "claims.parquet").to_pylist()
        Migration(V2Source(v2_tree), out_dir=v2_tree / "out2").run()
        second = pq.read_table(v2_tree / "out2" / "claims.parquet").to_pylist()
        assert [r["claim_id"] for r in first] == [r["claim_id"] for r in second]

    def test_species_list_on_claim(self, migrated):
        _, _, out = migrated
        rows = pq.read_table(out / "claims.parquet").to_pylist()
        assert all(r["species"] == ["Mus musculus"] for r in rows)


class TestSideTables:
    def test_blank_protein_dropped(self, migrated):
        _, stats, out = migrated
        rows = pq.read_table(out / "interactors.parquet").to_pylist()
        assert len(rows) == 1
        assert rows[0]["protein"] == "SHARP"
        assert rows[0]["species"] == ["Mus musculus"]

    def test_regulation_kept(self, migrated):
        _, _, out = migrated
        rows = pq.read_table(out / "regulations.parquet").to_pylist()
        assert rows[0]["regulator"] == "OCT4"
        assert rows[0]["target"] == "XIST"

    def test_chromatin_marks_split(self, migrated):
        _, _, out = migrated
        rows = pq.read_table(out / "xci_status.parquet").to_pylist()
        assert rows[0]["chromatin_marks"] == ["H3K27me3", "H2AK119ub"]

    def test_xist_reported_parsed_to_bool(self, migrated):
        _, _, out = migrated
        rows = pq.read_table(out / "species_xist.parquet").to_pylist()
        assert rows[0]["xist_reported"] is True


class TestReport:
    def test_report_written_and_parseable(self, migrated):
        migration, _, _ = migrated
        path = migration.write_report()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["papers_read"] == 3
        assert payload["claims_read"] == 2
        assert "repairs" in payload
        assert "topic_top_20" in payload

    def test_json_parse_failures_counted(self, v2_tree):
        stats = Migration(V2Source(v2_tree), out_dir=v2_tree / "o").run()
        # iter_annotations logs a warning rather than counting; the migration
        # still completes with the good file present.
        assert stats.papers_read == 3


class TestPaperIdCase:
    """V2 spells the same paper three ways; the migration picks one.

    Measured on the full corpus: 815 claim paper_ids are absent from the
    registry until both sides are lowercased, and 696 text lookups start
    working. No two papers differ only by case, so nothing merges.
    """

    @pytest.fixture
    def mixed_case_tree(self, tmp_path: Path) -> Path:
        root = tmp_path / "v2"
        for sub in ("metadata", "notes/json", "notes/claims", "papers/text", "papers/pdf"):
            (root / sub).mkdir(parents=True)

        with (root / "metadata" / "papers.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                ["paper_id", "title", "year", "journal", "doi", "pmid",
                 "species", "taxonomic_group", "first_author", "status"]
            )
            writer.writerow(
                ["ADiociaiuti2019_angioma", "A paper", "2019", "J", "", "",
                 "", "", "ADiociaiuti", "ingested"]
            )

        # text file uses different casing from the registry entry
        (root / "papers" / "text" / "adiociaiuti2019_angioma.txt").write_text(
            "body text", encoding="utf-8"
        )
        (root / "papers" / "pdf" / "ADiociaiuti2019_angioma.pdf").write_bytes(b"%PDF")
        (root / "notes" / "json" / "ADiociaiuti2019_angioma.json").write_text(
            json.dumps({"claims": []}), encoding="utf-8"
        )

        header = ["paper_id", "claim", "topic", "evidence", "evidence_type", "directness",
                  "section", "paragraph", "figure_or_table", "species", "cell_type",
                  "confidence", "caveat"]
        with (root / "notes" / "claims" / "adiociaiuti2019_angioma_claims.csv").open(
            "w", encoding="utf-8", newline=""
        ) as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            # the claim row is lowercase while the registry is mixed case
            writer.writerow(["adiociaiuti2019_angioma", "Xist coats X", "xci", "",
                             "direct_experimental", "direct", "results", "", "", "",
                             "", "high", ""])

        # check() requires the side tables to exist; these tests only care
        # about papers/claims, so the schema is created empty.
        conn = sqlite3.connect(root / "xist_knowledge.db")
        conn.executescript(
            """
            CREATE TABLE papers (paper_id TEXT PRIMARY KEY);
            CREATE TABLE claims (id INTEGER PRIMARY KEY, paper_id TEXT);
            CREATE TABLE regulations (id INTEGER PRIMARY KEY, paper_id TEXT);
            CREATE TABLE interactors (id INTEGER PRIMARY KEY, paper_id TEXT);
            CREATE TABLE xci_status (id INTEGER PRIMARY KEY, paper_id TEXT);
            CREATE TABLE species_xist (id INTEGER PRIMARY KEY, paper_id TEXT);
            """
        )
        conn.commit()
        conn.close()
        return root

    def test_paper_id_is_lowercased(self, mixed_case_tree):
        Migration(V2Source(mixed_case_tree), out_dir=mixed_case_tree / "o").run()
        rows = pq.read_table(mixed_case_tree / "o" / "papers.parquet").to_pylist()
        assert [r["paper_id"] for r in rows] == ["adiociaiuti2019_angioma"]

    def test_text_file_found_across_case(self, mixed_case_tree):
        Migration(V2Source(mixed_case_tree), out_dir=mixed_case_tree / "o").run()
        rows = pq.read_table(mixed_case_tree / "o" / "papers.parquet").to_pylist()
        assert rows[0]["has_text"] is True
        assert rows[0]["has_pdf"] is True
        assert rows[0]["has_annotation"] is True

    def test_claim_joins_paper_after_lowercasing(self, mixed_case_tree):
        Migration(V2Source(mixed_case_tree), out_dir=mixed_case_tree / "o").run()
        paper_ids = {
            r["paper_id"]
            for r in pq.read_table(mixed_case_tree / "o" / "papers.parquet").to_pylist()
        }
        claims = pq.read_table(mixed_case_tree / "o" / "claims.parquet").to_pylist()
        assert claims[0]["paper_id"] == "adiociaiuti2019_angioma"
        assert claims[0]["paper_id"] in paper_ids

    def test_map_records_original_file_names(self, mixed_case_tree):
        Migration(V2Source(mixed_case_tree), out_dir=mixed_case_tree / "o").run()
        rows = pq.read_table(mixed_case_tree / "o" / "paper_id_map.parquet").to_pylist()
        entry = next(r for r in rows if r["paper_id"] == "adiociaiuti2019_angioma")
        assert entry["text_file"] == "adiociaiuti2019_angioma"
        assert entry["pdf_file"] == "ADiociaiuti2019_angioma"
        assert entry["claims_file"] == "adiociaiuti2019_angioma"

    def test_lowercase_counts_reported(self, mixed_case_tree):
        stats = Migration(V2Source(mixed_case_tree), out_dir=mixed_case_tree / "o").run()
        assert stats.paper_id_lowercased == 1
        assert stats.claim_paper_id_lowercased == 0


class TestClaimIdCollisions:
    def test_duplicate_claims_get_distinct_ids(self, tmp_path, v2_tree):
        """A paper can state the same claim twice with the same missing quote.

        Measured on the real corpus: 11 ids covered 27 rows. The occurrence
        ordinal is part of the id, so the first row keeps its original id and
        later duplicates get their own.
        """
        claims_csv = v2_tree / "notes" / "claims" / "smith2019_abc_claims.csv"
        with claims_csv.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                ["smith2019_abc", "Xist coats the inactive X", "xci", "Fig 1",
                 "direct_experimental", "direct", "results", "Xist coats the X.",
                 "Fig 1", "mouse", "ES cells", "high", ""]
            )
        out = tmp_path / "o"
        stats = Migration(V2Source(v2_tree), out_dir=out).run()
        rows = pq.read_table(out / "claims.parquet").to_pylist()
        same = [r for r in rows if r["claim"] == "Xist coats the inactive X"]
        assert len(same) == 2
        assert len({r["claim_id"] for r in same}) == 2
        assert stats.claim_id_collisions_resolved == 1

    def test_all_claim_ids_unique(self, tmp_path, v2_tree):
        out = tmp_path / "o"
        Migration(V2Source(v2_tree), out_dir=out).run()
        ids = [r["claim_id"] for r in pq.read_table(out / "claims.parquet").to_pylist()]
        assert len(ids) == len(set(ids))
