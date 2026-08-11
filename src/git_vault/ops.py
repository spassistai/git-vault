"""High-level git-vault operations."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from git_vault import gitops
from git_vault.bundles import (
    BundleEntry,
    Manifest,
    bundle_filename,
    load_manifest,
    read_vault_json,
    read_vault_salt,
    save_manifest,
    sha256_file,
    write_vault_json,
)
from git_vault.crypto import (
    AuthError,
    decrypt,
    encrypt,
    export_vaultkey,
    get_master_password,
    import_vaultkey,
    new_salt,
    repo_key_from_password,
)
from git_vault.store import (
    StoreError,
    ensure_artifact_checkout,
    init_local_artifact_repo,
    pull_artifact,
    push_artifact,
)
from git_vault.workspace import Workspace, WorkspaceError, find_workspace, write_workspace

INCOMING_REF = "refs/git-vault/incoming"


class ConflictError(Exception):
    pass


class IntegrityError(Exception):
    pass


def _password_to_repo_key(repo_id: str, salt: bytes) -> bytes:
    password = get_master_password()
    return repo_key_from_password(password, repo_id, salt)


def resolve_repo_key(ws: Workspace, salt: bytes) -> bytes:
    key_path = ws.marker / "repo.key"
    if key_path.exists():
        data = key_path.read_bytes()
        if len(data) == 32:
            return data
        try:
            rid, key = import_vaultkey(data)
            if rid == ws.repo_id:
                return key
        except AuthError:
            pass
    return _password_to_repo_key(ws.repo_id, salt)


def _ensure_gitignore(root: Path) -> None:
    gi = root / ".gitignore"
    line = ".git-vault/"
    if gi.exists():
        text = gi.read_text(encoding="utf-8")
        if line in text.splitlines() or any(
            x.strip() == line or x.strip() == ".git-vault" for x in text.splitlines()
        ):
            return
        if text and not text.endswith("\n"):
            text += "\n"
        gi.write_text(text + line + "\n", encoding="utf-8")
    else:
        gi.write_text(line + "\n", encoding="utf-8")


def _sync_state(
    root: Path,
    local_head: str | None,
    remote_head: str | None,
) -> str:
    if not remote_head:
        return "remote_empty"
    if not local_head:
        return "local_empty"
    if local_head == remote_head:
        return "up_to_date"
    if gitops.is_ancestor(root, remote_head, local_head):
        return "ahead"
    if gitops.is_ancestor(root, local_head, remote_head):
        return "behind"
    return "diverged"


def _format_status(data: dict[str, Any]) -> str:
    lines = [
        f"repo_id:    {data['repo_id']}",
        f"remote:     {data['remote']}",
        f"last_seq:   {data['last_seq']}",
        f"local_HEAD: {data['local_head'] or '(none)'}",
    ]
    if data.get("error"):
        lines.append(f"remote:     unavailable ({data['error']})")
        return "\n".join(lines)
    lines.append(f"remote_HEAD:{data['remote_head'] or '(none)'}")
    lines.append(f"bundles:    {data['bundles']}")
    lines.append(f"sync:       {data['sync']}")
    return "\n".join(lines)


def _normalize_remote(remote: str) -> str:
    # Filesystem remotes must be stored absolute: the workspace's cwd differs
    # between commands (clone dest vs. original repo), so a relative path
    # written at init/clone time breaks later push/pull.
    if "://" in remote or re.match(r"^[^/@]+@[^/:]+:", remote):
        return remote
    return str(Path(remote).expanduser().resolve())


def cmd_init(repo_id: str | None, remote: str | None, cwd: Path | None = None) -> Workspace:
    root = (cwd or Path.cwd()).resolve()
    if not gitops.is_git_repo(root):
        raise WorkspaceError(f"not a git repository: {root}")
    if (root / ".git-vault").exists():
        raise WorkspaceError("already initialized (.git-vault exists)")

    if remote is None:
        raise WorkspaceError("--remote is required (artifact git URL or local path)")
    remote = _normalize_remote(remote)
    if repo_id is None:
        repo_id = root.name

    password = get_master_password(confirm=True)
    salt = new_salt()
    key = repo_key_from_password(password, repo_id, salt)

    cache = init_local_artifact_repo(remote, repo_id)
    write_vault_json(cache, repo_id, 0, salt)
    save_manifest(cache, Manifest.empty(repo_id), key, salt)
    push_artifact(cache, "git-vault: init empty vault")

    _ensure_gitignore(root)
    if not gitops.working_tree_clean(root) and gitops.rev_parse(root, "HEAD"):
        try:
            gitops.run_git("add", ".gitignore", cwd=root)
            status = gitops.run_git("status", "--porcelain", cwd=root)
            if status.stdout.strip():
                gitops.run_git(
                    "commit",
                    "-m",
                    "chore: ignore .git-vault marker",
                    cwd=root,
                )
        except gitops.GitError:
            pass

    return write_workspace(root, repo_id=repo_id, remote=remote, last_seq=0)


def cmd_status(
    cwd: Path | None = None,
    *,
    as_json: bool = False,
) -> str:
    ws = find_workspace(cwd)
    local_head = gitops.rev_parse(ws.root, "HEAD")
    data: dict[str, Any] = {
        "repo_id": ws.repo_id,
        "remote": ws.remote,
        "last_seq": ws.last_seq,
        "local_head": local_head,
        "remote_head": None,
        "bundles": None,
        "sync": None,
        "error": None,
    }

    try:
        cache = ensure_artifact_checkout(ws.remote)
        pull_artifact(cache)
        salt = read_vault_salt(cache)
        key = resolve_repo_key(ws, salt)
        manifest = load_manifest(cache, key)
        data["remote_head"] = manifest.head
        data["bundles"] = manifest.bundle_count
        data["sync"] = _sync_state(ws.root, local_head, manifest.head)
    except (StoreError, AuthError) as exc:
        data["error"] = str(exc)

    if as_json:
        return json.dumps(data, indent=2)
    return _format_status(data)


def cmd_push(cwd: Path | None = None) -> str:
    ws = find_workspace(cwd)
    if not gitops.working_tree_clean(ws.root):
        raise WorkspaceError("working tree not clean; commit or stash first")

    head = gitops.rev_parse(ws.root, "HEAD")
    if head is None:
        raise WorkspaceError("no commits to push")

    cache = ensure_artifact_checkout(ws.remote)
    try:
        pull_artifact(cache)
    except StoreError:
        pass

    salt = read_vault_salt(cache)
    key = resolve_repo_key(ws, salt)
    manifest = load_manifest(cache, key)
    if manifest.repo_id != ws.repo_id:
        raise IntegrityError(
            f"repo_id mismatch: local={ws.repo_id} manifest={manifest.repo_id}"
        )

    if manifest.head == head:
        return "already up to date"

    if manifest.head is not None:
        if not gitops.is_ancestor(ws.root, manifest.head, head):
            raise ConflictError(
                f"local HEAD is not a descendant of remote head {manifest.head[:12]}; "
                "pull/reconcile first"
            )
        rev_range = f"{manifest.head}..HEAD"
        from_rev = manifest.head
    else:
        rev_range = None
        from_rev = None

    seq = manifest.last_seq + 1
    rel = bundle_filename(seq)
    enc_path = cache / rel
    enc_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="git-vault-") as tmp:
        raw_bundle = Path(tmp) / "bundle"
        gitops.create_bundle(ws.root, raw_bundle, rev_range)
        enc_path.write_bytes(encrypt(key, raw_bundle.read_bytes()))

    entry = BundleEntry(
        seq=seq,
        file=rel,
        from_rev=from_rev,
        to=head,
        sha256=sha256_file(enc_path),
    )
    manifest.bundles.append(entry)
    manifest.head = head
    save_manifest(cache, manifest, key, salt)
    push_artifact(cache, f"git-vault: bundle {seq:06d}")
    ws.set_last_seq(seq)
    return f"pushed bundle {seq:06d} -> {head[:12]}"


def _apply_bundle(ws: Workspace, cache: Path, entry: BundleEntry, key: bytes) -> None:
    path = cache / entry.file
    if not path.exists():
        raise IntegrityError(f"missing bundle file {entry.file}")
    if sha256_file(path) != entry.sha256:
        raise IntegrityError(f"hash mismatch for {entry.file}")

    plaintext = decrypt(key, path.read_bytes())
    with tempfile.TemporaryDirectory(prefix="git-vault-") as tmp:
        raw = Path(tmp) / "bundle"
        raw.write_bytes(plaintext)
        gitops.fetch_bundle(ws.root, raw, f"HEAD:{INCOMING_REF}")
        local_head = gitops.rev_parse(ws.root, "HEAD")
        if local_head is None:
            gitops.run_git("checkout", "-B", "main", INCOMING_REF, cwd=ws.root)
        else:
            if entry.from_rev and local_head != entry.from_rev:
                if (
                    not gitops.is_ancestor(ws.root, entry.from_rev, "HEAD")
                    and local_head != entry.from_rev
                ):
                    raise ConflictError(
                        f"cannot apply bundle {entry.seq}: local HEAD {local_head[:12]} "
                        f"!= expected {entry.from_rev[:12]}"
                    )
            try:
                gitops.merge_ff_only(ws.root, INCOMING_REF)
            except gitops.GitError as exc:
                raise ConflictError(str(exc)) from exc

        tip = gitops.rev_parse(ws.root, "HEAD")
        if tip != entry.to:
            if tip and gitops.is_ancestor(ws.root, tip, entry.to):
                gitops.run_git("merge", "--ff-only", entry.to, cwd=ws.root)
            elif tip != entry.to:
                raise IntegrityError(
                    f"after bundle {entry.seq} HEAD is {tip}, expected {entry.to}"
                )


def cmd_pull(cwd: Path | None = None) -> str:
    ws = find_workspace(cwd)
    cache = ensure_artifact_checkout(ws.remote)
    pull_artifact(cache)
    salt = read_vault_salt(cache)
    key = resolve_repo_key(ws, salt)
    manifest = load_manifest(cache, key)
    if manifest.repo_id != ws.repo_id:
        raise IntegrityError(
            f"repo_id mismatch: local={ws.repo_id} manifest={manifest.repo_id}"
        )

    pending = [b for b in manifest.bundles if b.seq > ws.last_seq]
    if not pending:
        return "already up to date"

    for entry in pending:
        _apply_bundle(ws, cache, entry, key)
        ws.set_last_seq(entry.seq)

    return f"pulled {len(pending)} bundle(s); HEAD={gitops.rev_parse(ws.root, 'HEAD')}"


def cmd_clone(remote_url: str, directory: Path | None, key_file: Path | None = None) -> Path:
    remote_url = _normalize_remote(remote_url)
    try:
        cache = ensure_artifact_checkout(remote_url)
    except StoreError:
        cache = init_local_artifact_repo(remote_url, "unknown")
        try:
            pull_artifact(cache)
        except StoreError as exc:
            raise StoreError(f"cannot clone vault remote: {exc}") from exc

    vault_json = cache / "vault.json"
    if not vault_json.exists():
        raise StoreError("remote is not a git-vault artifact repo (no vault.json)")

    meta = read_vault_json(cache)
    repo_id = str(meta["repo_id"])
    salt = read_vault_salt(cache)

    dest = (directory or Path.cwd() / Path(repo_id).name).resolve()
    if dest.exists() and any(dest.iterdir()):
        raise WorkspaceError(f"destination not empty: {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    gitops.init_repo(dest, bare=False)

    if key_file is not None:
        key_repo_id, key = import_vaultkey(key_file.read_bytes())
        if key_repo_id != repo_id:
            raise AuthError(f"vaultkey repo_id {key_repo_id} != vault {repo_id}")
    else:
        key = _password_to_repo_key(repo_id, salt)
    manifest = load_manifest(cache, key)
    ws = write_workspace(dest, repo_id=repo_id, remote=remote_url, last_seq=0)
    if key_file is not None:
        key_path = ws.marker / "repo.key"
        key_path.write_bytes(key)
        key_path.chmod(0o600)

    for entry in manifest.bundles:
        _apply_bundle(ws, cache, entry, key)
        ws.set_last_seq(entry.seq)

    return dest


def cmd_export_key(out: Path, cwd: Path | None = None) -> None:
    ws = find_workspace(cwd)
    cache = ensure_artifact_checkout(ws.remote)
    pull_artifact(cache)
    salt = read_vault_salt(cache)
    key = resolve_repo_key(ws, salt)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(export_vaultkey(ws.repo_id, key))
    out.chmod(0o600)


def cmd_unlock(key_file: Path, cwd: Path | None = None) -> str:
    """Store shared key for this workspace (no master password needed afterwards)."""
    ws = find_workspace(cwd)
    repo_id, key = import_vaultkey(key_file.read_bytes())
    if repo_id != ws.repo_id:
        raise AuthError(f"vaultkey repo_id {repo_id} != workspace {ws.repo_id}")
    key_path = ws.marker / "repo.key"
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    return f"unlocked {ws.repo_id} (repo key stored in .git-vault/repo.key)"
