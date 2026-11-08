"""Normalize regulator names so the same factor is one factor.

`regulations` has 3,286 rows naming 1,339 distinct regulators, but several of
those distinctions are accidents of capitalisation or annotation style:

    Tsix | TSIX          326 rows across two spellings
    JPX | Jpx            121
    Nanog | NANOG        107
    Rnf12 (RLIM) | Rnf12 (Rlim) | RNF12 (RLIM) | RNF12 (Rlim)
    Oct4 | Oct4 (POU5F1) | OCT4 | oct4 (Pou5f1)

A query for "which factors repress Xist" that groups by `regulator` splits each
of these into separate bars. Folding case takes 1,339 to 1,226; stripping a
parenthesised alias takes it further.

Two rules, both mechanical and checkable:

1. **Case-fold.** Gene names are case-insensitive in prose; `Tsix` and `TSIX` are
   the same gene and no annotation intended a distinction.
2. **Strip a trailing parenthesised alias** when the text outside the parentheses
   is non-empty: `Oct4 (POU5F1)` becomes `Oct4`. The alias is a synonym, not a
   different regulator.

What is deliberately *not* done: merging `Oct4` with `POU5F1`, or `Rnf12` with
`Rlim`. Those are the same gene under two names, but deciding that requires
external knowledge of gene synonymy, and a wrong merge silently combines two
different factors into one bar. The alias is kept in the `alias` column so a
reader can see what was folded away, and a future synonym table can use it.

The original `regulator` string is preserved in `regulator_raw`: the normalization
is a query-time convenience, not a correction of the stored annotation.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _utf8_stdout() -> None:
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


import duckdb  # noqa: E402

REGULATOR_SCHEMA = pa.schema(
    [
        ("paper_id", pa.string()),
        ("regulator_raw", pa.string()),
        ("regulator", pa.string()),
        ("alias", pa.string()),
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

# A trailing "(ALIAS)" at the end of a name. Anchored to the end because gene
# names can legitimately contain parentheses mid-string ("Rnf12/RLIM") and only
# the trailing form is an annotation habit rather than part of the name.
_TRAILING_ALIAS = re.compile(r"\s*\(([^()]*)\)\s*$")

# Only an alias that looks like a gene symbol is folded away. Gene symbols here
# are short, alphanumeric, and hyphen/slash-tolerant: Pou5f1, Zfp42, si-XIST,
# RLIM, C181/C275. Requiring a digit or an all-caps token rejects English words
# that happen to sit in parentheses -- "(artificial)", "(X-Reactivation)" --
# while keeping the genuine aliases.
#
# The parentheses in this data also carry experimental conditions --
# "Oxygen tension (5% vs 20%)", "Tetracycline/doxycycline-inducible promoter
# (artificial)", "Doxycycline-induced Xist (TX allele, nls-rtTA from ROSA26)" --
# and stripping those would delete what distinguishes the rows, which is the
# opposite of what normalization is for.
_GENE_SYMBOL = re.compile(r"^[A-Za-z][A-Za-z0-9\-/]{1,14}$")


def _looks_like_gene_symbol(text: str) -> bool:
    if not _GENE_SYMBOL.match(text):
        return False
    has_digit = any(ch.isdigit() for ch in text)
    is_caps_token = text.upper() == text and sum(ch.isalpha() for ch in text) >= 2
    return has_digit or is_caps_token


def normalize_regulator(raw: str | None) -> tuple[str, str]:
    """Return (canonical, alias) for one regulator name.

    Empty or sentinel input returns ("", ""). The canonical form is the display
    form: original capitalisation of the stripped text, not lowercased, because
    `Tsix` reads correctly and `tsix` does not -- case is folded for grouping,
    not for display.
    """
    text = (raw or "").strip()
    if not text:
        return "", ""

    alias = ""
    match = _TRAILING_ALIAS.search(text)
    if match:
        candidate = match.group(1).strip()
        outer = text[: match.start()].strip()
        # Keep the parentheses when nothing would remain ("(RLIM)" alone is the
        # name) and when the parenthesised text is a condition rather than a
        # gene symbol.
        if outer and _looks_like_gene_symbol(candidate):
            alias = candidate
            text = outer

    return text, alias


def build(conn: duckdb.DuckDBPyConnection, out_path: Path) -> dict:
    rows = conn.execute(
        """
        SELECT paper_id, regulator, target, direction, species, cell_type,
               developmental_stage, evidence_type, directness, confidence,
               provenance_id
        FROM regulations
        """
    ).fetchall()

    records: list[dict] = []
    raw_names: set[str] = set()
    canonical_names: set[str] = set()
    folded: dict[str, set[str]] = {}

    for (
        paper_id, regulator, target, direction, species, cell_type,
        stage, evidence_type, directness, confidence, provenance_id,
    ) in rows:
        canonical, alias = normalize_regulator(regulator)
        raw = (regulator or "").strip()
        raw_names.add(raw)
        canonical_names.add(canonical)
        folded.setdefault(canonical.lower(), set()).add(canonical)
        records.append(
            {
                "paper_id": paper_id,
                "regulator_raw": raw,
                "regulator": canonical,
                "alias": alias,
                "target": target,
                "direction": direction,
                "species": species,
                "cell_type": cell_type,
                "developmental_stage": stage,
                "evidence_type": evidence_type,
                "directness": directness,
                "confidence": confidence,
                "provenance_id": provenance_id,
            }
        )

    table = pa.Table.from_pylist(records, REGULATOR_SCHEMA)
    tmp = out_path.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, out_path)

    # Spellings that differ only by case are guaranteed to be one gene; report
    # them so the folding is visible rather than implied.
    case_variants = {k: sorted(v) for k, v in folded.items() if len(v) > 1}

    return {
        "rows": len(records),
        "distinct_raw": len(raw_names),
        "distinct_canonical": len(canonical_names),
        "folded_by_case": len(raw_names) - len(canonical_names),
        "case_variant_groups": len(case_variants),
        "case_variant_examples": dict(list(case_variants.items())[:8]),
        "bytes": out_path.stat().st_size,
    }


def main() -> None:
    _utf8_stdout()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    data_dir = Path(os.environ.get("XIST_KB_DATA") or "data_local_lowercase")
    gold = data_dir / "gold" if (data_dir / "gold").is_dir() else data_dir

    # Through the query layer so a missing index falls back to Parquet views:
    # requiring the index here would make the rebuild order circular, since the
    # index is built from the parquet this function writes.
    from xist_kb.query.engine import connect

    conn = connect(gold_dir=gold, index_file=data_dir / "index" / "xist.duckdb")
    try:
        report = build(conn, gold / "regulators.parquet")
    finally:
        conn.close()
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
