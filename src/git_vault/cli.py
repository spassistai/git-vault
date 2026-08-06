"""CLI entrypoint. Commands are stubs until MVP crypto/sync lands."""

from __future__ import annotations

from enum import IntEnum
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(
    name="git-vault",
    help="Incremental encrypted git sync (append-only age bundles).",
    no_args_is_help=True,
)


class ExitCode(IntEnum):
    OK = 0
    AUTH = 2
    CONFLICT = 3
    NETWORK = 4
    INTEGRITY = 5


def _not_implemented(name: str) -> None:
    typer.echo(f"git-vault {name}: not implemented yet (see DESIGN.md)", err=True)
    raise typer.Exit(code=1)


@app.command()
def init(
    repo_id: Optional[str] = typer.Option(None, "--repo-id", help="Canonical vault id"),
    remote: Optional[str] = typer.Option(None, "--remote", help="Git remote for artifact repo"),
) -> None:
    """Create local .git-vault marker and remote artifact layout."""
    _ = (repo_id, remote)
    _not_implemented("init")


@app.command()
def clone(
    remote_url: str = typer.Argument(..., help="Vault artifact remote URL"),
    directory: Optional[Path] = typer.Argument(None, help="Target directory"),
) -> None:
    """Clone vault remote and materialize plaintext working tree."""
    _ = (remote_url, directory)
    _not_implemented("clone")


@app.command()
def pull() -> None:
    """Fetch new encrypted bundles, decrypt, unbundle."""
    _not_implemented("pull")


@app.command()
def push() -> None:
    """Bundle new commits, encrypt, append to remote vault."""
    _not_implemented("push")


@app.command()
def status() -> None:
    """Show vault sync status for the current working tree."""
    if not (Path.cwd() / ".git-vault").is_dir():
        typer.echo("Not a git-vault working tree (missing .git-vault/).", err=True)
        raise typer.Exit(code=1)
    _not_implemented("status")


@app.command("export-key")
def export_key(
    out: Path = typer.Option(..., "--out", help="Path for *.vaultkey"),
) -> None:
    """Export per-repo key for sharing (not the master password)."""
    _ = out
    _not_implemented("export-key")


@app.command()
def unlock(
    key_file: Path = typer.Option(..., "--key-file", help="Shared *.vaultkey"),
) -> None:
    """Unlock local vault with a shared repo key."""
    _ = key_file
    _not_implemented("unlock")


if __name__ == "__main__":
    app()
