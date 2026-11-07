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
    ├── bronze/
    ├── silver/
    ├── gold/
    └── index/
```

Set `XIST_KB_DATA=/Data7/luyx/XIST-KB/data` in `app/.env` so the code writes
outside the checkout.

## Network

Outbound HTTPS works (Crossref returns 200). `api.anthropic.com` returns 403
from a bare `curl` — that is expected, since the endpoint rejects unauthenticated
requests; it does not mean the host is blocked. Verify with a real API call
before assuming egress is restricted.

## Mirrors

Package installs from PyPI are slow (a 20 MB duckdb wheel took ~50 s). If this
becomes painful, an internal mirror or `pip config set global.index-url` to a
domestic mirror would help; ask before changing global pip config.
