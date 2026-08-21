"""Deployment maintenance commands for managed QwenPaw seeds."""

from __future__ import annotations

import json
from pathlib import Path

import click

from qwenpaw.constant import WORKING_DIR
from qwenpaw.working_sync import ManagedSyncError, sync_managed_seed

DEFAULT_SEED_DIR = Path("/app/share/qwenpaw-seed")


def _render_result(result: object) -> str:
    payload = result.as_dict()
    summary = payload["summary"]
    lines = [
        f"Seed: {payload['seed_id']}",
        f"Target: {payload['target']}",
        "Mode: " + ("dry-run" if payload["dry_run"] else "apply"),
        "Summary: " + ", ".join(
            f"{name}={count}" for name, count in sorted(summary.items())
        ),
    ]
    for action in payload["actions"]:
        lines.append(
            f"{action['action'].upper():10} {action['kind']:16} "
            f"{action['path']} ({action['reason']})"
        )
    if payload.get("report_path"):
        lines.append(f"Report: {payload['report_path']}")
    if payload.get("backup_path"):
        lines.append(f"Backup: {payload['backup_path']}")
    return "\n".join(lines)


@click.group("deploy")
def deploy_group() -> None:
    """Deployment maintenance commands."""


@deploy_group.command("sync-managed")
@click.option(
    "--seed",
    type=click.Path(path_type=Path),
    default=DEFAULT_SEED_DIR,
    show_default=True,
    help="Read-only materialized seed directory from the image.",
)
@click.option(
    "--target",
    type=click.Path(path_type=Path),
    default=lambda: WORKING_DIR,
    show_default=True,
    help="Existing working-directory PVC mount to reconcile.",
)
@click.option(
    "--apply",
    is_flag=True,
    help="Apply the managed synchronization.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print the plan without writing files.",
)
@click.option("--yes", is_flag=True, help="Confirm a non-interactive apply.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option(
    "--report",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional report file path. Apply mode writes the report atomically.",
)
def sync_managed(
    seed: Path,
    target: Path,
    apply: bool,
    dry_run: bool,
    yes: bool,
    json_output: bool,
    report: Path | None,
) -> None:
    """Safely reconcile image-managed files into an existing PVC."""
    if apply and dry_run:
        raise click.UsageError("--apply and --dry-run cannot be used together")
    if apply and not yes:
        click.confirm(
            "Apply managed seed files to the existing working directory?",
            abort=True,
        )
    try:
        result = sync_managed_seed(
            seed,
            target,
            apply=apply,
            report_path=report,
        )
    except ManagedSyncError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        click.echo(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    else:
        click.echo(_render_result(result))
