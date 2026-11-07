#!/usr/bin/env bash
# One-time V2 -> Parquet migration on the lab server.
#
# Expects v2src.tar.gz in the data root (papers.csv, notes/json,
# notes/claims, xist_knowledge.db). Unpacks into data/v2src/ and runs the
# migration, leaving Parquet in data/gold/ and the report beside it.
set -euo pipefail

ROOT=/Data7/luyx/XIST-KB
APP=$ROOT/app
DATA=$ROOT/data
SRC=$DATA/v2src

cd "$APP"

if [ ! -f "$DATA/v2src.tar.gz" ]; then
    echo "missing $DATA/v2src.tar.gz" >&2
    exit 1
fi

mkdir -p "$SRC"
tar -xzf "$DATA/v2src.tar.gz" -C "$SRC"

# The archive holds relative paths from the V2 checkout root.
if [ ! -f "$SRC/metadata/papers.csv" ]; then
    echo "archive did not contain metadata/papers.csv" >&2
    ls -R "$SRC" | head -20 >&2
    exit 1
fi

.venv/bin/xist migrate-v2 "$SRC" --report "$DATA/quality_report.json"

echo
echo "=== gold layer ==="
ls -lh "$DATA/gold"
echo
echo "=== free space ==="
df -h "$DATA" | tail -1
