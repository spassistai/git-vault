"""Local cache of the remote artifact repository."""

from __future__ import annotations

from pathlib import Path

from git_vault import gitops
from git_vault.paths import artifact_cache_path


class StoreError(Exception):
    pass


def ensure_artifact_checkout(remote: str) -> Path:
    """Clone or update the artifact repo into the cache; return its path."""
    cache = artifact_cache_path(remote)
    git_dir = cache / ".git"
    try:
        if git_dir.exists():
            gitops.run_git("remote", "set-url", "origin", remote, cwd=cache)
            gitops.run_git("fetch", "origin", cwd=cache)
            # Prefer main, fall back to master
            for branch in ("main", "master"):
                r = gitops.run_git(
                    "rev-parse",
                    "--verify",
                    f"origin/{branch}",
                    cwd=cache,
                    check=False,
                )
                if r.returncode == 0:
                    gitops.run_git("checkout", "-B", branch, f"origin/{branch}", cwd=cache)
                    break
            return cache

        # Fresh clone
        # If remote is empty / not yet a repo, clone may fail — caller handles init case.
        parent = cache.parent
        parent.mkdir(parents=True, exist_ok=True)
        if cache.exists() and any(cache.iterdir()):
            # incomplete cache
            pass
        gitops.run_git("clone", remote, str(cache))
        return cache
    except gitops.GitError as exc:
        raise StoreError(str(exc)) from exc


def init_local_artifact_repo(remote: str, repo_id: str) -> Path:
    """
    Prepare artifact store.

    - If remote is an existing local path (possibly bare), clone/init into cache.
    - For brand-new remotes: create content in cache and push.
    """
    cache = artifact_cache_path(remote)

    # Local path remote that does not exist yet → create bare repo
    remote_path = Path(remote)
    if _looks_like_local_path(remote) and not remote_path.exists():
        gitops.init_repo(remote_path, bare=True)

    if (cache / ".git").exists():
        return cache

    try:
        gitops.run_git("clone", remote, str(cache))
    except gitops.GitError:
        # Empty/nonexistent remote: init in cache and set origin
        if cache.exists():
            for child in cache.iterdir():
                if child.name != ".git":
                    break
            else:
                pass
        cache.mkdir(parents=True, exist_ok=True)
        if not (cache / ".git").exists():
            gitops.init_repo(cache, bare=False)
        gitops.run_git("checkout", "-B", "main", cwd=cache, check=False)
        # If no commits yet, orphan branch is fine after first commit
        r = gitops.run_git("remote", cwd=cache, check=False)
        if "origin" not in (r.stdout or ""):
            gitops.run_git("remote", "add", "origin", remote, cwd=cache)
        else:
            gitops.run_git("remote", "set-url", "origin", remote, cwd=cache)

    readme = cache / "README.md"
    if not readme.exists():
        readme.write_text(
            f"# git-vault artifacts\n\nEncrypted vault for `{repo_id}`.\n"
            "Use `git-vault` to push/pull — do not edit files here manually.\n",
            encoding="utf-8",
        )
    (cache / "bundles").mkdir(exist_ok=True)
    gitkeep = cache / "bundles" / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.write_text("", encoding="utf-8")
    return cache


def push_artifact(cache: Path, message: str) -> None:
    try:
        _ensure_git_identity(cache)
        # Ensure we are on a branch
        branch = gitops.current_branch(cache)
        if branch is None:
            gitops.run_git("checkout", "-B", "main", cwd=cache)
            branch = "main"
        gitops.run_git("add", "-A", cwd=cache)
        status = gitops.run_git("status", "--porcelain", cwd=cache)
        if not status.stdout.strip():
            return
        # First commit may need allow if user config requires etc.
        gitops.run_git("commit", "-m", message, cwd=cache)
        # Push — set upstream on first push
        r = gitops.run_git(
            "push", "-u", "origin", "HEAD", cwd=cache, check=False
        )
        if r.returncode != 0:
            raise StoreError((r.stderr or r.stdout or "push failed").strip())
    except gitops.GitError as exc:
        raise StoreError(str(exc)) from exc


def _ensure_git_identity(cwd: Path) -> None:
    for key, value in (
        ("user.email", "git-vault@localhost"),
        ("user.name", "git-vault"),
    ):
        r = gitops.run_git("config", "--get", key, cwd=cwd, check=False)
        if r.returncode != 0 or not r.stdout.strip():
            gitops.run_git("config", key, value, cwd=cwd)


def pull_artifact(cache: Path) -> None:
    try:
        gitops.run_git("fetch", "origin", cwd=cache)
        for branch in ("main", "master"):
            r = gitops.run_git(
                "rev-parse", "--verify", f"origin/{branch}", cwd=cache, check=False
            )
            if r.returncode == 0:
                gitops.run_git("checkout", "-B", branch, f"origin/{branch}", cwd=cache)
                return
    except gitops.GitError as exc:
        raise StoreError(str(exc)) from exc


def _looks_like_local_path(remote: str) -> bool:
    if remote.startswith(("git@", "http://", "https://", "ssh://")):
        return False
    if remote.startswith("file://"):
        return True
    return True
