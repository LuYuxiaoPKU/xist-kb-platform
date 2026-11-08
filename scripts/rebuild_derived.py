#!/usr/bin/env python3
"""Rebuild the derived Gold tables and the index, in the one correct order.

The order is not obvious and getting it wrong wastes 20 minutes:

1. `migrate-v2` produces the base tables (papers, claims, provenance, ...).
   It does not touch anything derived.
2. `chunks` comes straight from the text files.
3. `claim_provenance` (tiers) needs claims and the text; it does not need the
   index.
4. `paper_scope`, `species_fill`, `regulators` read through the query layer,
   which falls back to views over Parquet when no index exists. They must run
   *before* the index is built, not after: the index materialises them.
5. `index` last, because it copies every table in.

Building the index before step 4 produces an index missing those three tables,
and the API then reports their panels as unavailable -- which looks like a bug in
the query layer rather than a build-order mistake.

Each step is idempotent and replaces its output atomically. The script stops at
the first failure rather than continuing with a half-built layer.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def run(label: str, *args: str, env: dict[str, str]) -> None:
    print(f"\n=== {label} ===", flush=True)
    result = subprocess.run(
        [PY, "-I", *args], cwd=ROOT, env=env, capture_output=True, text=True, errors="replace"
    )
    tail = (result.stdout or "").strip().splitlines()[-12:]
    for line in tail:
        print("  " + line)
    if result.returncode != 0:
        print(f"  FAILED ({result.returncode})", flush=True)
        for line in (result.stderr or "").strip().splitlines()[-20:]:
            print("  " + line)
        raise SystemExit(1)


def main() -> None:
    data = Path(os.environ.get("XIST_KB_DATA") or ROOT / "data_local_lowercase")
    env = dict(os.environ)
    env["XIST_KB_DATA"] = str(data)
    if "XIST_KB_TEXT_DIR" not in env:
        # The V2 checkout sits beside this repository in the author's layout.
        candidate = ROOT.parent / "XIST_Project_V2" / "papers" / "text"
        if candidate.is_dir():
            env["XIST_KB_TEXT_DIR"] = str(candidate)

    print(json.dumps({"data": str(data), "text": env.get("XIST_KB_TEXT_DIR")}, indent=1))

    run("chunks", "scripts/build_chunks.py", env=env)
    run("tiers", "-m", "xist_kb.build.tiers", env=env)
    run("paper_scope", "scripts/build_paper_scope.py", env=env)
    run("species_fill", "scripts/build_species_fill.py", env=env)
    run("regulators", "scripts/build_regulators.py", env=env)
    run("index", "-m", "xist_kb.build.fts", env=env)

    print("\nall derived layers rebuilt")


if __name__ == "__main__":
    main()
