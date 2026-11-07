"""Unified CLI for xist-kb-platform.

Stability: the subcommands and their flags are the public interface. Internal
Python APIs may change without notice; anything scripted against this tool
should call the CLI or the HTTP API, not import from xist_kb directly.
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="XIST/XCI literature knowledge base platform.",
)
console = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


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


@app.command("migrate-v2")
def migrate_v2(
    source: Path = typer.Argument(..., help="Path to the V2 project checkout"),
    out: Path | None = typer.Option(None, help="Output directory (default: gold layer)"),
    report: Path | None = typer.Option(None, help="Quality report path"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Migrate a V2 checkout into Gold-layer Parquet."""
    from xist_kb.ingest.legacy import V2Source
    from xist_kb.ingest.migrate_v2 import Migration

    _setup_logging(verbose)

    source = source.resolve()
    if not source.exists():
        console.print(f"[red]source not found: {source}[/red]")
        raise typer.Exit(code=2)

    v2 = V2Source(source)
    missing = v2.check()
    if missing:
        console.print(f"[red]source is incomplete, missing: {missing}[/red]")
        raise typer.Exit(code=2)

    migration = Migration(v2, out_dir=out)
    stats = migration.run()
    report_path = migration.write_report(report)

    console.print(f"[green]migrated {stats.papers_read} papers, {stats.claims_read} claims[/green]")
    console.print(f"report: {report_path}")
    console.print(f"output: {migration.out_dir}")


if __name__ == "__main__":
    app()
