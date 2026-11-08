# Lab server: deployment notes

Target host: `162.105.248.197`, user `luyx`, data root `/Data7/luyx/XIST-KB`.

## The system is old

The host runs a CentOS 7-era userland: **glibc 2.17**, **gcc 4.8.5**. This
breaks the default `pip install` path in a specific way: pip falls back to
building packages from source, and numpy's meson build fails immediately with
`Compiler cython cannot compile programs`. The error names numpy, but the real
constraint is the old toolchain.

**Always install with binary wheels only:**

```bash
.venv/bin/pip install --only-binary=:all: 'duckdb>=1.2,<1.3' 'pyarrow>=16' 'pandas>=2.2' 'numpy>=1.26,<3'
.venv/bin/pip install --only-binary=:all: -e '.[dev,link]'
```

Highest versions confirmed to have `manylinux_2_17_x86_64` wheels for
CPython 3.13 on this host:

| package | newest usable | note |
|---|---|---|
| duckdb | 1.2.2 | 1.3+ has no glibc 2.17 wheel |
| pyarrow | 20.0.0 | |
| pandas | 2.3.2 | |
| numpy | 2.2.6 | |

`duckdb` is pinned in `pyproject.toml` for this reason. If a future dependency
has no manylinux_2_17 wheel, the options are: find an older version, or build
it in a container with a newer glibc and copy the wheel over.

## Python and Node

- Python: 3.13.5 at `/Data7/luyx/Share/Software/anaconda3/bin/python3`
- Node: **v22.22.2** at `/Data7/Software/Claude_Code/nodejs/bin/node`

The `node` on the default PATH is v16, which is too old for the frontend build
and makes `npm` print a misleading warning. Invoke the v22 binaries explicitly:

```bash
export PATH=/Data7/Software/Claude_Code/nodejs/bin:$PATH
node --version   # v22.22.2
```

## Layout

```
/Data7/luyx/XIST-KB/
├── app/           # this repository (git clone)
└── data/          # Parquet layers, PDFs — never in git
    ├── gold/      # 13 parquet tables, 290 MB
    ├── index/     # xist.duckdb, 1.6 GB, materialised + FTS
    └── v2/papers/text/   # 13,502 paper texts, 677 MB
```

Set `XIST_KB_DATA=/Data7/luyx/XIST-KB/data` in `app/.env` so the code writes
outside the checkout. `XIST_KB_TEXT_DIR` defaults to
`$XIST_KB_DATA/v2/papers/text`, which is where the texts were placed.

## Running it

```bash
cd /Data7/luyx/XIST-KB/app
./deploy/serve.sh start     # background, restart loop, PID in run/xist-kb.pid
./deploy/serve.sh status    # also runs the health check
./deploy/serve.sh stop
```

Port **8420** on 127.0.0.1. Reach it with an SSH tunnel:

```bash
ssh -L 8420:127.0.0.1:8420 luyx@162.105.248.197
```

then open `http://127.0.0.1:8420/`. Binding externally instead requires
`XIST_KB_HOST=0.0.0.0` plus `XIST_KB_ALLOWED_NETS`: the API has one optional
shared key, not per-user accounts.

`run/` is not in git. The loop is the supervised process and uvicorn is its
child; `stop` kills the loop first so it cannot restart the child.

## Rebuilding the data

`scripts/rebuild_derived.py` runs the five derived builds and the index in the
only order that works (chunks → tiers → paper_scope → species_fill →
regulators → index). The index materialises every table, but the three
scope/species/regulator builders read through the query layer, which falls back
to Parquet views only when no index exists — so building the index first yields
an index missing three tables and the API reports those panels as unavailable.

Rebuild after any change to `migrate_v2.py`: the parquet is the output, and a
code fix not followed by a re-run leaves the old data in place. That is how 16
duplicate `claim_id`s survived a "fixed" commit and only surfaced when the
server deployment checked `count(*)-count(DISTINCT claim_id)`.

## Network

Outbound HTTPS works (Crossref returns 200). `api.anthropic.com` returns 403
from a bare `curl` — that is expected, since the endpoint rejects unauthenticated
requests; it does not mean the host is blocked. Verify with a real API call
before assuming egress is restricted.

`github.com:443` **is** unreachable: `git fetch` fails with `Failed to connect to
github.com port 443 after 127229 ms`. See Mirrors below.

## Mirrors

Package installs from PyPI are slow (a 20 MB duckdb wheel took ~50 s). If this
becomes painful, an internal mirror or `pip config set global.index-url` to a
domestic mirror would help; ask before changing global pip config.

### GitHub: fetch goes through a mirror

Fetch and push are pointed at different URLs (2026-11-09), so `git fetch` and
`git pull` work while `push` stays on the canonical remote:

```bash
git remote set-url        origin https://ghproxy.net/https://github.com/LuYuxiaoPKU/xist-kb-platform.git
git remote set-url --push origin https://github.com/LuYuxiaoPKU/xist-kb-platform.git
```

Measured from this host: `ghproxy.net` completes `git fetch` in ~5 s;
`ghfast.top` also serves the repo and is a drop-in replacement;
`gitclone.com` returns 502; `hub.fastgit.org` and `mirror.ghproxy.com` time out.
A bare `curl https://ghproxy.net/https://github.com` returns 403 — that is the
proxy refusing a bare repo-less path, not a blocked mirror. Test with
`git ls-remote`, not `curl`:

```bash
git ls-remote origin      # prints 40-hex HEAD in a few seconds when healthy
```

Push from this host does not work (no credentials, and github.com is
unreachable). That is fine — this checkout is read-only.

If both mirrors die, fall back to carrying a bundle over scp: run
`git bundle create /tmp/x.bundle master` locally, `scp` it over, then
`git fetch /tmp/x.bundle '+refs/heads/master:refs/remotes/origin/master'` and
`git merge --ff-only origin/master`. The leading `+` is required because the
server's history diverged once during a commit-email rewrite.
