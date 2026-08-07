"""End-to-end local vault sync without GitHub."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

os.environ["GIT_VAULT_FAST_KDF"] = "1"
os.environ["GIT_VAULT_PASSWORD"] = "test-master-password"

from git_vault import ops  # noqa: E402
from git_vault import gitops  # noqa: E402


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_project(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "checkout", "-B", "main")
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "init")


def test_init_push_clone_pull(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GIT_VAULT_PASSWORD", "test-master-password")
    monkeypatch.setenv("GIT_VAULT_FAST_KDF", "1")

    bare = tmp_path / "artifact.git"
    project = tmp_path / "project"
    _init_project(project)

    ops.cmd_init(repo_id="example.com/demo", remote=str(bare), cwd=project)
    msg = ops.cmd_push(cwd=project)
    assert "pushed bundle" in msg

    # Second commit + incremental push
    (project / "note.txt").write_text("more\n", encoding="utf-8")
    _git(project, "add", "note.txt")
    _git(project, "commit", "-m", "note")
    msg2 = ops.cmd_push(cwd=project)
    assert "000002" in msg2 or "pushed bundle" in msg2

    dest = tmp_path / "clone"
    ops.cmd_clone(str(bare), dest)
    assert (dest / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert (dest / "note.txt").read_text(encoding="utf-8") == "more\n"
    assert (dest / ".git-vault" / "repo_id").read_text(encoding="utf-8").strip() == "example.com/demo"

    # Push from clone after edit; pull into original
    (dest / "note.txt").write_text("more\nedited\n", encoding="utf-8")
    _git(dest, "add", "note.txt")
    _git(dest, "config", "user.email", "test@example.com")
    _git(dest, "config", "user.name", "Test")
    _git(dest, "commit", "-m", "edit")
    ops.cmd_push(cwd=dest)

    ops.cmd_pull(cwd=project)
    assert (project / "note.txt").read_text(encoding="utf-8") == "more\nedited\n"
