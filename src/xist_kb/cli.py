"""Unified CLI for xist-kb-platform.

Stability: the subcommands and their flags are the public interface. Internal
Python APIs may change without notice; anything scripted against this tool
should call the CLI or the HTTP API, not import from xist_kb directly.
"""

from __future__ import annotations

import typer
from rich.console import Console

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="XIST/XCI literature knowledge base platform.",
)
console = Console()


@app.command()
def version() -> None:
    """Print the installed version."""
    from xist_kb import __version__

    console.print(f"xist-kb-platform {__version__}")


@app.command()
def status() -> None:
    """Report which data layers are present on disk."""
    from xist_kb.paths import DATA_DIR

    if not DATA_DIR.exists():
        console.print(f"[yellow]no data directory at {DATA_DIR}[/yellow]")
        raise typer.Exit(code=0)

    for layer in ("bronze", "silver", "gold"):
        path = DATA_DIR / layer
        if not path.exists():
            console.print(f"{layer:8} [dim]absent[/dim]")
            continue
        files = sorted(p for p in path.rglob("*") if p.is_file())
        size = sum(p.stat().st_size for p in files)
        console.print(f"{layer:8} {len(files):5d} files  {size / 1e6:8.1f} MB")


if __name__ == "__main__":
    app()
