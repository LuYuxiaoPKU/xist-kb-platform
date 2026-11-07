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


@app.command()
def stats() -> None:
    """Print aggregate counts from the Gold layer."""
    from xist_kb.query import search
    from xist_kb.query.engine import connect, describe

    conn = connect()
    counts = describe(conn)
    console.print("[bold]rows[/bold]")
    for name, n in counts.items():
        console.print(f"  {name:15} {n:>8,}")

    s = search.stats(conn)
    console.print("\n[bold]topics[/bold]")
    for row in s["topics"][:15]:
        console.print(f"  {row['topic']:28} {row['count']:>8,}")
    console.print("\n[bold]status[/bold]")
    for row in s["statuses"]:
        console.print(f"  {row['status']:28} {row['count']:>8,}")


@app.command()
def search(
    text: str | None = typer.Option(None, help="Substring match on claim or quote"),
    topic: list[str] = typer.Option([], help="Topic (repeatable)"),
    species: list[str] = typer.Option([], help="Species, exact (repeatable)"),
    confidence: list[str] = typer.Option([], help="Confidence (repeatable)"),
    year_from: int | None = typer.Option(None),
    year_to: int | None = typer.Option(None),
    limit: int = typer.Option(20),
) -> None:
    """Query claims from the Gold layer."""
    from xist_kb.query import search as q
    from xist_kb.query.engine import connect

    conn = connect()
    rows, total = q.search_claims(
        conn,
        q.ClaimFilter(
            topics=list(topic),
            species=list(species),
            confidence=list(confidence),
            year_from=year_from,
            year_to=year_to,
            text=text,
            limit=limit,
        ),
    )
    console.print(f"[dim]{total:,} matching claims, showing {len(rows)}[/dim]\n")
    for row in rows:
        year = row.get("year") or "----"
        console.print(f"[bold]{row['topic']}[/bold] · {row['confidence']} · {year}")
        console.print(f"  {row['claim']}")
        if row.get("title"):
            console.print(f"  [dim]{row['title']} ({row['paper_id']})[/dim]")
        console.print()


@app.command()
def paper(paper_id: str = typer.Argument(...)) -> None:
    """Show one paper and its claims."""
    from xist_kb.query import search as q
    from xist_kb.query.engine import connect

    conn = connect()
    p = q.get_paper(conn, paper_id)
    if p is None:
        console.print(f"[red]no such paper: {paper_id}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[bold]{p['title']}[/bold]")
    console.print(f"{p.get('journal') or '?'} · {p.get('year') or '?'} · {p['status']}")
    if p.get("doi"):
        console.print(f"doi: {p['doi']}")
    console.print()

    claims = q.get_claims_for_paper(conn, paper_id)
    console.print(f"[bold]{len(claims)} claims[/bold]")
    for c in claims:
        console.print(f"  [{c['topic']}] {c['claim']}")
        if c.get("quote"):
            console.print(f"    [dim]> {c['quote'][:160]}[/dim]")


if __name__ == "__main__":
    app()
