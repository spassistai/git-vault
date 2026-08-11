"""End-to-end local vault sync without GitHub."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

os.environ["GIT_VAULT_FAST_KDF"] = "1"
os.environ["GIT_VAULT_PASSWORD"] = "test-master-password"
os.environ["GIT_VAULT_PASSWORD_CONFIRM"] = "test-master-password"

from git_vault import ops  # noqa: E402
from git_vault.bundles import read_vault_json  # noqa: E402
from git_vault.crypto import AuthError  # noqa: E402
from git_vault.ops import ConflictError  # noqa: E402
from git_vault.paths import artifact_cache_path  # noqa: E402


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


def _set_pw(monkeypatch: pytest.MonkeyPatch, password: str, *, confirm: str | None = None) -> None:
    monkeypatch.setenv("GIT_VAULT_PASSWORD", password)
    monkeypatch.setenv("GIT_VAULT_PASSWORD_CONFIRM", confirm if confirm is not None else password)
    monkeypatch.setenv("GIT_VAULT_FAST_KDF", "1")


def test_init_push_clone_pull(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _set_pw(monkeypatch, "test-master-password")

    bare = tmp_path / "artifact.git"
    project = tmp_path / "project"
    _init_project(project)

    ops.cmd_init(repo_id="example.com/demo", remote=str(bare), cwd=project)
    msg = ops.cmd_push(cwd=project)
    assert "pushed bundle" in msg

    (project / "note.txt").write_text("more\n", encoding="utf-8")
    _git(project, "add", "note.txt")
    _git(project, "commit", "-m", "note")
    msg2 = ops.cmd_push(cwd=project)
    assert "pushed bundle" in msg2

    dest = tmp_path / "clone"
    ops.cmd_clone(str(bare), dest)
    assert (dest / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert (dest / "note.txt").read_text(encoding="utf-8") == "more\n"
    assert (dest / ".git-vault" / "repo_id").read_text(encoding="utf-8").strip() == "example.com/demo"

    (dest / "note.txt").write_text("more\nedited\n", encoding="utf-8")
    _git(dest, "add", "note.txt")
    _git(dest, "config", "user.email", "test@example.com")
    _git(dest, "config", "user.name", "Test")
    _git(dest, "commit", "-m", "edit")
    ops.cmd_push(cwd=dest)

    ops.cmd_pull(cwd=project)
    assert (project / "note.txt").read_text(encoding="utf-8") == "more\nedited\n"


def test_salt_portable_across_homes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same master password + vault.json salt works with a fresh HOME (new machine)."""
    home1 = tmp_path / "home1"
    home2 = tmp_path / "home2"
    bare = tmp_path / "artifact.git"
    project = tmp_path / "project"
    _init_project(project)

    monkeypatch.setenv("HOME", str(home1))
    _set_pw(monkeypatch, "portable-secret")
    ops.cmd_init(repo_id="example.com/portable", remote=str(bare), cwd=project)
    ops.cmd_push(cwd=project)

    # Salt must be on the remote, not only in local config
    cache = artifact_cache_path(str(bare))
    meta = read_vault_json(cache)
    assert "salt" in meta
    assert len(bytes.fromhex(meta["salt"])) == 16

    monkeypatch.setenv("HOME", str(home2))
    _set_pw(monkeypatch, "portable-secret")
    dest = tmp_path / "other-machine"
    ops.cmd_clone(str(bare), dest)
    assert (dest / "README.md").read_text(encoding="utf-8") == "hello\n"


def test_wrong_password_on_clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    bare = tmp_path / "artifact.git"
    project = tmp_path / "project"
    _init_project(project)

    _set_pw(monkeypatch, "correct-password")
    ops.cmd_init(repo_id="example.com/demo", remote=str(bare), cwd=project)
    ops.cmd_push(cwd=project)

    _set_pw(monkeypatch, "wrong-password")
    with pytest.raises(AuthError):
        ops.cmd_clone(str(bare), tmp_path / "fail-clone")


def test_init_password_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    project = tmp_path / "project"
    _init_project(project)
    _set_pw(monkeypatch, "one", confirm="two")
    with pytest.raises(AuthError, match="do not match"):
        ops.cmd_init(
            repo_id="example.com/demo",
            remote=str(tmp_path / "artifact.git"),
            cwd=project,
        )


def test_diverged_push_conflicts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _set_pw(monkeypatch, "test-master-password")

    bare = tmp_path / "artifact.git"
    a = tmp_path / "a"
    _init_project(a)
    ops.cmd_init(repo_id="example.com/demo", remote=str(bare), cwd=a)
    ops.cmd_push(cwd=a)

    b = tmp_path / "b"
    ops.cmd_clone(str(bare), b)
    _git(b, "config", "user.email", "test@example.com")
    _git(b, "config", "user.name", "Test")

    (a / "a.txt").write_text("a\n", encoding="utf-8")
    _git(a, "add", "a.txt")
    _git(a, "commit", "-m", "from-a")
    ops.cmd_push(cwd=a)

    (b / "b.txt").write_text("b\n", encoding="utf-8")
    _git(b, "add", "b.txt")
    _git(b, "commit", "-m", "from-b")
    with pytest.raises(ConflictError):
        ops.cmd_push(cwd=b)


def test_status_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _set_pw(monkeypatch, "test-master-password")

    bare = tmp_path / "artifact.git"
    project = tmp_path / "project"
    _init_project(project)
    ops.cmd_init(repo_id="example.com/demo", remote=str(bare), cwd=project)
    ops.cmd_push(cwd=project)

    raw = ops.cmd_status(cwd=project, as_json=True)
    data = json.loads(raw)
    assert data["repo_id"] == "example.com/demo"
    assert data["sync"] == "up_to_date"
    assert data["bundles"] == 1
    assert data["error"] is None
    assert data["local_head"] == data["remote_head"]


def test_relative_remote_path_survives_cwd_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _set_pw(monkeypatch, "test-master-password")

    bare = tmp_path / "artifact.git"
    project = tmp_path / "project"
    _init_project(project)

    monkeypatch.chdir(tmp_path)
    ops.cmd_init(repo_id="demo", remote="./artifact.git", cwd=project)
    ops.cmd_push(cwd=project)

    dest = tmp_path / "clone"
    ops.cmd_clone("./artifact.git", dest)

    (dest / "extra.txt").write_text("x\n", encoding="utf-8")
    _git(dest, "add", "extra.txt")
    _git(dest, "config", "user.email", "test@example.com")
    _git(dest, "config", "user.name", "Test")
    _git(dest, "commit", "-m", "extra")

    # push/pull run from the workspace dir, not where init/clone happened
    monkeypatch.chdir(dest)
    ops.cmd_push(cwd=dest)
    ops.cmd_pull(cwd=project)
    assert (project / "extra.txt").read_text(encoding="utf-8") == "x\n"


def test_clone_with_key_file_no_master_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _set_pw(monkeypatch, "test-master-password")

    bare = tmp_path / "artifact.git"
    project = tmp_path / "project"
    _init_project(project)
    ops.cmd_init(repo_id="demo", remote=str(bare), cwd=project)
    ops.cmd_push(cwd=project)

    key_file = tmp_path / "demo.vaultkey"
    ops.cmd_export_key(key_file, cwd=project)

    # employee machine: wrong/absent master password, only the vaultkey
    monkeypatch.setenv("HOME", str(tmp_path / "home2"))
    _set_pw(monkeypatch, "not-the-master-password")
    dest = tmp_path / "employee"
    ops.cmd_clone(str(bare), dest, key_file=key_file)
    assert (dest / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert (dest / ".git-vault" / "repo.key").exists()

    # and push/pull work without ever knowing the master password
    (dest / "work.txt").write_text("done\n", encoding="utf-8")
    _git(dest, "add", "work.txt")
    _git(dest, "config", "user.email", "emp@example.com")
    _git(dest, "config", "user.name", "Emp")
    _git(dest, "commit", "-m", "work")
    ops.cmd_push(cwd=dest)

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _set_pw(monkeypatch, "test-master-password")
    ops.cmd_pull(cwd=project)
    assert (project / "work.txt").read_text(encoding="utf-8") == "done\n"

    # wrong key file is rejected
    other = tmp_path / "other"
    _init_project(other)
    ops.cmd_init(repo_id="other", remote=str(tmp_path / "other.git"), cwd=other)
    other_key = tmp_path / "other.vaultkey"
    ops.cmd_export_key(other_key, cwd=other)
    with pytest.raises(AuthError):
        ops.cmd_clone(str(bare), tmp_path / "employee2", key_file=other_key)
