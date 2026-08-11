"""CLI entrypoint for git-vault."""

from __future__ import annotations

from enum import IntEnum
from pathlib import Path
from typing import Optional

import typer

from git_vault import ops
from git_vault.crypto import AuthError
from git_vault.ops import ConflictError, IntegrityError
from git_vault.store import StoreError
from git_vault.workspace import WorkspaceError

app = typer.Typer(
    name="git-vault",
    help="Incremental encrypted git sync (append-only encrypted bundles).",
    no_args_is_help=True,
)


class ExitCode(IntEnum):
    OK = 0
    AUTH = 2
    CONFLICT = 3
    NETWORK = 4
    INTEGRITY = 5


def _fail(message: str, code: int) -> None:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(code=code)


def _handle(exc: Exception) -> None:
    if isinstance(exc, AuthError):
        _fail(str(exc), ExitCode.AUTH)
    if isinstance(exc, ConflictError):
        _fail(str(exc), ExitCode.CONFLICT)
    if isinstance(exc, StoreError):
        _fail(str(exc), ExitCode.NETWORK)
    if isinstance(exc, IntegrityError):
        _fail(str(exc), ExitCode.INTEGRITY)
    if isinstance(exc, WorkspaceError):
        _fail(str(exc), 1)
    _fail(str(exc), 1)


@app.command()
def init(
    repo_id: Optional[str] = typer.Option(None, "--repo-id", help="Canonical vault id"),
    remote: Optional[str] = typer.Option(
        None, "--remote", help="Git remote for artifact repo (URL or local path)"
    ),
) -> None:
    """Create local .git-vault marker and initialize remote artifact layout."""
    try:
        ws = ops.cmd_init(repo_id=repo_id, remote=remote)
    except Exception as exc:
        _handle(exc)
        return
    typer.echo(f"initialized vault {ws.repo_id}")
    typer.echo(f"artifact remote: {ws.remote}")


@app.command()
def clone(
    remote_url: str = typer.Argument(..., help="Vault artifact remote URL"),
    directory: Optional[Path] = typer.Argument(None, help="Target directory"),
    key_file: Optional[Path] = typer.Option(
        None, "--key-file", help="Shared *.vaultkey (skips master password)"
    ),
) -> None:
    """Clone vault remote and materialize plaintext working tree."""
    try:
        dest = ops.cmd_clone(remote_url, directory, key_file=key_file)
    except Exception as exc:
        _handle(exc)
        return
    typer.echo(f"cloned into {dest}")


@app.command()
def pull() -> None:
    """Fetch new encrypted bundles, decrypt, unbundle."""
    try:
        msg = ops.cmd_pull()
    except Exception as exc:
        _handle(exc)
        return
    typer.echo(msg)


@app.command()
def push() -> None:
    """Bundle new commits, encrypt, append to remote vault."""
    try:
        msg = ops.cmd_push()
    except Exception as exc:
        _handle(exc)
        return
    typer.echo(msg)


@app.command()
def status(
    as_json: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON status"
    ),
) -> None:
    """Show vault sync status for the current working tree."""
    try:
        msg = ops.cmd_status(as_json=as_json)
    except Exception as exc:
        _handle(exc)
        return
    typer.echo(msg)


@app.command("export-key")
def export_key(
    out: Path = typer.Option(..., "--out", help="Path for *.vaultkey"),
) -> None:
    """Export per-repo key for sharing (not the master password)."""
    try:
        ops.cmd_export_key(out)
    except Exception as exc:
        _handle(exc)
        return
    typer.echo(f"wrote {out}")


@app.command()
def unlock(
    key_file: Path = typer.Option(..., "--key-file", help="Shared *.vaultkey"),
) -> None:
    """Unlock local vault with a shared repo key."""
    try:
        msg = ops.cmd_unlock(key_file)
    except Exception as exc:
        _handle(exc)
        return
    typer.echo(msg)


if __name__ == "__main__":
    app()
