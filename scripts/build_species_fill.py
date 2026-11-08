"""Fill in claims.species where the claim itself recorded none -- and decide
how much of that gap is fillable at all.

8,288 of 115,674 claims (7.2%) have an empty species list. The measurement that
matters came before any filling: **6,488 of those 8,288 (78%) contain no organism
word at all** -- no "human", "mouse", "Drosophila", "yeast", no cell line. They
are statements like "Xist is a gene within the X inactivation center" or
"Sambamba introduces full parallelized data processing". Those are true of a
model organism or of none; the annotator left the field blank because the claim
does not say, and filling it from the paper would manufacture precision the text
does not have.

So filling is deliberately narrow, and the table it produces is an optional
inference layer rather than an edit to `claims.parquet`.

Sources, in descending order of reliability, both additionally restricted to
Latin binomials:

1. **The paper's species_xist record**, only when it names exactly one species.
   Measured: single-species records agree with the paper's own claim-level
   annotations 84% of the time (6,604/7,841); multi-species records only 5%
   (157/3,260). A multi-valued record says "this paper touches four organisms",
   true of a comparative review and false of the claim "Xist is a gene in the
   Xic" -- propagating it would label a statement about eutherians with
   Caenorhabditis elegans.

2. **Sibling claims in the same paper**, only when every annotated claim agrees
   on one species and the paper is not out of scope. 40% of papers with
   species-annotated claims are internally mixed, so an agreeing paper is
   informative and a mixed one says nothing. Out-of-scope papers are skipped:
   "ZAP-X low energy (3 MV) ... reduced penumbra" inherited Homo sapiens from its
   paper's radiotherapy claims, dressing an off-topic statement as annotated.

Only values matching a Latin binomial are accepted. The source data contains
clades ("Mammalia", "Theria"), missed common names ("chimpanzee", "macaque"),
viruses ("HIV-1") and corrupted field residue ("not reported not_reported XIST
expression"); copying any of those into a new table would launder them.

Result on the current corpus: 1,562 filled (18.8% of the gap, 1.4% of all
claims), 6,726 left empty. That is the honest ceiling for this approach, not a
shortfall to grind at -- the remaining claims mostly do not name an organism.
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _utf8_stdout() -> None:
    """Make the Windows console print UTF-8.

    Windows defaults stdout to GBK, which raises on the typographic characters
    that appear in paper text. Done inside `main` rather than at import: a test
    that loads this module must not have its own stdout replaced and closed,
    which is what happened when this ran at module level.
    """
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


import duckdb  # noqa: E402

from xist_kb.vocab import normalize_species_list  # noqa: E402

SPECIES_FILL_SCHEMA = pa.schema(
    [
        ("claim_id", pa.string()),
        ("paper_id", pa.string()),
        ("species", pa.list_(pa.string())),
        ("source", pa.string()),
        ("confidence", pa.string()),
    ]
)

# Values that mean "no species recorded", not an organism.
_EMPTY_SPECIES = frozenset(
    {"", "not reported", "not_reported", "unknown", "n/a", "na", "none"}
)

# A Latin binomial pattern alone is not enough: "Multiple species" and
# "Mammalian cells" both match it. The whitelist is the actual gate -- these are
# the organisms the corpus annotates, and anything else is left unfilled rather
# than guessed at. It is not a list of every organism in biology; it is the
# intersection of "appears in this corpus" and "we are confident it is a species".
KNOWN_SPECIES = frozenset(
    {
        "Homo sapiens",
        "Mus musculus",
        "Rattus norvegicus",
        "Drosophila melanogaster",
        "Saccharomyces cerevisiae",
        "Schizosaccharomyces pombe",
        "Caenorhabditis elegans",
        "Arabidopsis thaliana",
        "Danio rerio",
        "Gallus gallus",
        "Xenopus laevis",
        "Xenopus tropicalis",
        "Bos taurus",
        "Sus scrofa",
        "Oryctolagus cuniculus",
        "Macaca mulatta",
        "Pan troglodytes",
        "Gorilla gorilla",
        "Pongo abelii",
        "Nomascus leucogenys",
        "Callithrix jacchus",
        "Cricetulus griseus",
        "Mesocricetus auratus",
        "Canis lupus familiaris",
        "Felis catus",
        "Equus caballus",
        "Ovis aries",
        "Capra hircus",
        "Oryzias latipes",
        "Takifugu rubripes",
        "Tetraodon nigroviridis",
        "Petromyzon marinus",
        "Ciona intestinalis",
        "Strongylocentrotus purpuratus",
        "Nematostella vectensis",
        "Neurospora crassa",
        "Aspergillus nidulans",
        "Candida albicans",
        "Plasmodium falciparum",
        "Trypanosoma brucei",
        "Leishmania major",
        "Tetrahymena thermophila",
        "Paramecium tetraurelia",
        "Dictyostelium discoideum",
        "Physcomitrella patens",
        "Oryza sativa",
        "Zea mays",
        "Glycine max",
        "Solanum lycopersicum",
        "Nicotiana tabacum",
        "Vitis vinifera",
        "Populus trichocarpa",
        "Selaginella moellendorffii",
        "Chlamydomonas reinhardtii",
        "Volvox carteri",
        "Escherichia coli",
        "Bacillus subtilis",
        "Mycobacterium tuberculosis",
        "Pseudomonas aeruginosa",
        "Staphylococcus aureus",
        "Streptomyces coelicolor",
        "Synechocystis sp.",
        "Thermus thermophilus",
        "Deinococcus radiodurans",
        "Sulfolobus solfataricus",
        "Methanocaldococcus jannaschii",
        "Halobacterium salinarum",
    }
)


def _known_species_only(values: list[str]) -> list[str]:
    return [v for v in values if v in KNOWN_SPECIES]

SOURCE_PAPER = "species_xist"
SOURCE_SIBLING = "sibling_claims"


def _usable(raw: str | None) -> bool:
    return bool(raw) and raw.strip().lower() not in _EMPTY_SPECIES


def build(conn: duckdb.DuckDBPyConnection, out_path: Path) -> dict:
    empty = conn.execute(
        "SELECT claim_id, paper_id FROM claims WHERE species IS NULL OR len(species) = 0"
    ).fetchall()

    # Source 1: the paper's species_xist record, but only when it names exactly
    # one species. Measured: for single-species records the paper's own claims
    # agree on one species 84% of the time (6,604/7,841); for multi-species
    # records they agree only 5% of the time (157/3,260). A multi-valued record
    # says "this paper touches four organisms", which is true of comparative
    # reviews and false of the individual claim "Xist is a gene in the Xic".
    # Propagating it would label a statement about eutherians with
    # Caenorhabditis elegans.
    paper_species: dict[str, list[str]] = {}
    for paper_id, raw in conn.execute(
        "SELECT paper_id, species FROM species_xist WHERE species IS NOT NULL"
    ).fetchall():
        if not _usable(raw):
            continue
        species = normalize_species_list(raw)
        if len(species) == 1:
            kept = _known_species_only(species)
            if kept:
                paper_species[paper_id] = kept

    # Source 2: sibling claims, keyed by paper, only where every annotated
    # claim in the paper agrees on one species. A mixed paper's blank claim
    # cannot inherit either answer without inventing evidence -- 40% of papers
    # with species-annotated claims are internally mixed.
    #
    # Papers judged out of scope are skipped: their claims are about something
    # other than this knowledge base's subject, and inheriting a species from
    # them would dress up an off-topic statement as an annotated one. Measured:
    # "ZAP-X low energy (3 MV) and short SAD ... reduced penumbra" inherited
    # Homo sapiens from its paper's radiotherapy claims.
    sibling_species: dict[str, list[str]] = {}
    out_of_scope = {
        pid
        for (pid,) in conn.execute(
            "SELECT paper_id FROM paper_scope WHERE scope = 'out_of_scope'"
        ).fetchall()
    }
    for paper_id, kinds in conn.execute(
        """
        SELECT paper_id, list_sort(list_distinct(list(s))) AS kinds
        FROM (
            SELECT paper_id, unnest(species) AS s
            FROM claims WHERE species IS NOT NULL AND len(species) > 0
        )
        GROUP BY 1
        HAVING len(kinds) = 1
        """
    ).fetchall():
        if paper_id in out_of_scope:
            continue
        cleaned = _known_species_only([s for s in kinds if _usable(s)])
        if cleaned:
            sibling_species[paper_id] = cleaned

    records: list[dict] = []
    tally = {SOURCE_PAPER: 0, SOURCE_SIBLING: 0, "unfilled": 0}
    for claim_id, paper_id in empty:
        if paper_id in paper_species:
            records.append(
                {
                    "claim_id": claim_id,
                    "paper_id": paper_id,
                    "species": paper_species[paper_id],
                    "source": SOURCE_PAPER,
                    "confidence": "inferred",
                }
            )
            tally[SOURCE_PAPER] += 1
        elif paper_id in sibling_species:
            records.append(
                {
                    "claim_id": claim_id,
                    "paper_id": paper_id,
                    "species": sibling_species[paper_id],
                    "source": SOURCE_SIBLING,
                    "confidence": "inferred",
                }
            )
            tally[SOURCE_SIBLING] += 1
        else:
            tally["unfilled"] += 1

    table = pa.Table.from_pylist(records, SPECIES_FILL_SCHEMA)
    tmp = out_path.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, out_path)

    return {
        "claims_without_species": len(empty),
        "filled": len(records),
        "filled_pct": round(100 * len(records) / max(len(empty), 1), 1),
        "by_source": tally,
        "still_empty": tally["unfilled"],
        "bytes": out_path.stat().st_size,
    }


def main() -> None:
    _utf8_stdout()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    data_dir = Path(os.environ.get("XIST_KB_DATA") or "data_local_lowercase")
    gold = data_dir / "gold" if (data_dir / "gold").is_dir() else data_dir
    index = data_dir / "index" / "xist.duckdb"
    if not index.exists():
        raise SystemExit(f"index database not found at {index}")

    conn = duckdb.connect(str(index), read_only=True)
    report = build(conn, gold / "species_fill.parquet")
    conn.close()
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
