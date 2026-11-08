"""Run the API server.

Port 8420 rather than 8000: this machine already has a service on 8000, and on
the lab server several people run their own uvicorns. The default lives here so
`python -m xist_kb.api.serve` and the deploy scripts agree; `XIST_KB_PORT`
overrides it, and `--port` overrides both.

`--host 0.0.0.0` is only for the lab deployment, where an SSH tunnel or the
`XIST_KB_ALLOWED_NETS` allowlist limits who can reach it. The local default is
loopback: binding a 296k-paper mirror of the literature to every interface by
accident is not something a default should do.
"""

from __future__ import annotations

import argparse
import os

DEFAULT_PORT = 8420


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the XIST knowledge base API")
    parser.add_argument(
        "--host",
        default=os.environ.get("XIST_KB_HOST", "127.0.0.1"),
        help="interface to bind (default 127.0.0.1; use 0.0.0.0 on the server)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("XIST_KB_PORT", DEFAULT_PORT)),
        help=f"port to listen on (default {DEFAULT_PORT}, or $XIST_KB_PORT)",
    )
    parser.add_argument("--reload", action="store_true", help="reload on source changes")
    parser.add_argument(
        "--log-level",
        default=os.environ.get("XIST_KB_LOG_LEVEL", "info"),
        help="uvicorn log level (default info)",
    )
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        "xist_kb.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
