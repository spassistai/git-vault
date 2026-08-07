"""Thin wrappers around git subprocess calls."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(Exception):
    def __init__(self, message: str, *, returncode: int | None = None):
        super().__init__(message)
        self.returncode = returncode


def run_git(
    *args: str,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = ["git", *args]
    result = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=capture,
        check=False,
    )
    if check and result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise GitError(err or f"git {' '.join(args)} failed", returncode=result.returncode)
    return result


def is_git_repo(path: Path) -> bool:
    r = run_git("rev-parse", "--is-inside-work-tree", cwd=path, check=False)
    return r.returncode == 0 and r.stdout.strip() == "true"


def rev_parse(cwd: Path, rev: str = "HEAD") -> str | None:
    r = run_git("rev-parse", "--verify", rev, cwd=cwd, check=False)
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def is_ancestor(cwd: Path, maybe_ancestor: str, rev: str = "HEAD") -> bool:
    r = run_git(
        "merge-base",
        "--is-ancestor",
        maybe_ancestor,
        rev,
        cwd=cwd,
        check=False,
    )
    return r.returncode == 0


def working_tree_clean(cwd: Path) -> bool:
    r = run_git("status", "--porcelain", cwd=cwd)
    return r.stdout.strip() == ""


def current_branch(cwd: Path) -> str | None:
    r = run_git("symbolic-ref", "--short", "HEAD", cwd=cwd, check=False)
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def create_bundle(cwd: Path, out: Path, rev_range: str | None) -> None:
    """Create a git bundle. rev_range None => all history reachable from HEAD."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if rev_range is None:
        run_git("bundle", "create", str(out), "HEAD", cwd=cwd)
    else:
        run_git("bundle", "create", str(out), rev_range, cwd=cwd)


def fetch_bundle(cwd: Path, bundle: Path, refspec: str) -> None:
    run_git("fetch", str(bundle), refspec, cwd=cwd)


def merge_ff_only(cwd: Path, rev: str) -> None:
    run_git("merge", "--ff-only", rev, cwd=cwd)


def init_repo(path: Path, bare: bool = False) -> None:
    path.mkdir(parents=True, exist_ok=True)
    args = ["init"]
    if bare:
        args.append("--bare")
    run_git(*args, cwd=path)


def clone_repo(remote: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_git("clone", remote, str(dest))


def add_all_commit_push(cwd: Path, message: str, remote: str = "origin", branch: str = "main") -> None:
    run_git("add", "-A", cwd=cwd)
    # Allow empty? No — if nothing staged, status should have prevented this.
    r = run_git("status", "--porcelain", cwd=cwd)
    if not r.stdout.strip():
        return
    run_git("commit", "-m", message, cwd=cwd)
    # Ensure branch name
    cur = current_branch(cwd) or branch
    run_git("push", "-u", remote, cur, cwd=cwd)
