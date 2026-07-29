import uuid
from pathlib import Path

import typer

from jose.db.session import SessionLocal
from jose.services.collection import collect_source
from jose.services.platform_detection import detect_platforms_for_vc_sources, render_source_catalog
from jose.services.source_import import classify_workbook, commit_import, summarize
from jose.services.tasks import enqueue_collect_all, worker_loop
from jose.services.users import get_or_create_default_user

app = typer.Typer(help="JOSE command-line interface")

_DEFAULT_CATALOG_PATH = typer.Argument("/docs/source-catalog.md")


@app.command("seed")
def seed() -> None:
    """Create the default development user."""
    with SessionLocal() as session:
        user = get_or_create_default_user(session)
        typer.echo(f"Default user ready: {user.email} ({user.id})")


@app.command("import-sources")
def import_sources(
    path: Path,
    preview: bool = typer.Option(
        False, help="Show what would happen without writing to the database"
    ),
) -> None:
    """Import source URLs from Scott's Excel workbook."""
    if not path.exists():
        raise typer.BadParameter(f"File does not exist: {path}")
    with SessionLocal() as session:
        user = get_or_create_default_user(session)
        if preview:
            outcomes = classify_workbook(session, user, path)
            counts = summarize(outcomes)
            typer.echo(
                f"Preview: {counts['create']} to create, {counts['update']} to update, "
                f"{counts['skip']} to skip, {counts['flag']} flagged"
            )
            for outcome in outcomes:
                if outcome.action == "flag":
                    typer.echo(f"  FLAG row {outcome.row_number}: {outcome.url} — {outcome.reason}")
        else:
            run = commit_import(session, user, path, filename=path.name)
            typer.echo(
                f"Imported sources: {run.created_count} created, {run.updated_count} updated, "
                f"{run.skipped_count} skipped, {run.flagged_count} flagged"
            )


@app.command("detect-vc-platforms")
def detect_vc_platforms(catalog_path: Path = _DEFAULT_CATALOG_PATH) -> None:
    """Probe VC portfolio sources and record their platform/adapter status."""
    with SessionLocal() as session:
        user = get_or_create_default_user(session)
        results = detect_platforms_for_vc_sources(session, user)
        catalog_text = render_source_catalog(session, user)
    catalog_path.write_text(catalog_text)
    for result in results:
        if result.status == "error":
            typer.echo(f"  ERROR      {result.source_name}: {result.error}")
        else:
            typer.echo(
                f"  {result.status.upper():<10} {result.source_name}: "
                f"adapter={result.adapter} platform={result.detected_platform}"
            )
    typer.echo(f"Wrote {catalog_path}")


@app.command("collect-source")
def collect_source_command(source_id: uuid.UUID) -> None:
    """Run a source collector immediately."""
    with SessionLocal() as session:
        run = collect_source(session, source_id)
    typer.echo(
        f"Run {run.id}: {run.status}; found={run.jobs_found}; "
        f"created={run.jobs_created}; updated={run.jobs_updated}; rejected={run.jobs_rejected}"
    )


@app.command("enqueue-collect-all")
def enqueue_all(force: bool = typer.Option(False, help="Ignore daily idempotency key")) -> None:
    """Queue one collection task for every enabled source."""
    with SessionLocal() as session:
        user = get_or_create_default_user(session)
        tasks = enqueue_collect_all(session, user, force=force)
    typer.echo(f"Queued {len(tasks)} source collection tasks")


@app.command("worker")
def worker(once: bool = typer.Option(False, help="Process at most one task")) -> None:
    """Run the database-backed JOSE worker."""
    worker_loop(once=once)


if __name__ == "__main__":
    app()
