"""High-level git-vault operations."""

from __future__ import annotations

import tempfile
from pathlib import Path

from git_vault import gitops
from git_vault.bundles import (
    BundleEntry,
    Manifest,
    bundle_filename,
    load_manifest,
    save_manifest,
    sha256_file,
    write_vault_json,
)
from git_vault.crypto import (
    AuthError,
    export_vaultkey,
    get_master_password,
    import_vaultkey,
    repo_key_from_password,
)
from git_vault.store import StoreError, ensure_artifact_checkout, init_local_artifact_repo, pull_artifact, push_artifact
from git_vault.workspace import Workspace, WorkspaceError, find_workspace, write_workspace

INCOMING_REF = "refs/git-vault/incoming"


class ConflictError(Exception):
    pass


class IntegrityError(Exception):
    pass


def _repo_key_for(repo_id: str) -> bytes:
    password = get_master_password()
    return repo_key_from_password(password, repo_id)


def resolve_repo_key(ws: Workspace) -> bytes:
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
    return _repo_key_for(ws.repo_id)


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


def cmd_init(repo_id: str | None, remote: str | None, cwd: Path | None = None) -> Workspace:
    root = (cwd or Path.cwd()).resolve()
    if not gitops.is_git_repo(root):
        raise WorkspaceError(f"not a git repository: {root}")
    if (root / ".git-vault").exists():
        raise WorkspaceError("already initialized (.git-vault exists)")

    if remote is None:
        raise WorkspaceError("--remote is required (artifact git URL or local path)")
    if repo_id is None:
        repo_id = root.name

    cache = init_local_artifact_repo(remote, repo_id)
    write_vault_json(cache, repo_id, 0)
    key = _repo_key_for(repo_id)
    save_manifest(cache, Manifest.empty(repo_id), key)
    push_artifact(cache, "git-vault: init empty vault")

    _ensure_gitignore(root)
    # Keep tree pushable: commit .gitignore if we touched it and identity works.
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


def cmd_status(cwd: Path | None = None) -> str:
    ws = find_workspace(cwd)
    lines = [
        f"repo_id:   {ws.repo_id}",
        f"remote:    {ws.remote}",
        f"last_seq:  {ws.last_seq}",
    ]
    head = gitops.rev_parse(ws.root, "HEAD")
    lines.append(f"local_HEAD: {head or '(none)'}")

    try:
        cache = ensure_artifact_checkout(ws.remote)
        pull_artifact(cache)
        key = resolve_repo_key(ws)
        manifest = load_manifest(cache, key)
        lines.append(f"remote_HEAD: {manifest.head or '(none)'}")
        lines.append(f"bundles:   {manifest.bundle_count}")
        if head and manifest.head and head != manifest.head:
            if gitops.is_ancestor(ws.root, manifest.head, head):
                lines.append("sync:      local ahead (need push)")
            elif gitops.is_ancestor(ws.root, head, manifest.head):
                lines.append("sync:      local behind (need pull)")
            else:
                lines.append("sync:      diverged")
        elif head and manifest.head and head == manifest.head:
            lines.append("sync:      up to date")
        elif not manifest.head:
            lines.append("sync:      remote empty")
    except (StoreError, AuthError) as exc:
        lines.append(f"remote:    unavailable ({exc})")
    return "\n".join(lines)


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
        pass  # may be first push to freshly inited remote

    key = resolve_repo_key(ws)
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
                f"local HEAD is not a descendant of remote head {manifest.head[:12]}; pull/reconcile first"
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
        plaintext = raw_bundle.read_bytes()
        from git_vault.crypto import encrypt

        enc_path.write_bytes(encrypt(key, plaintext))

    digest = sha256_file(enc_path)
    entry = BundleEntry(
        seq=seq,
        file=rel,
        from_rev=from_rev,
        to=head,
        sha256=digest,
    )
    manifest.bundles.append(entry)
    manifest.head = head
    save_manifest(cache, manifest, key)
    push_artifact(cache, f"git-vault: bundle {seq:06d}")
    ws.set_last_seq(seq)
    return f"pushed bundle {seq:06d} -> {head[:12]}"


def _apply_bundle(ws: Workspace, cache: Path, entry: BundleEntry, key: bytes) -> None:
    path = cache / entry.file
    if not path.exists():
        raise IntegrityError(f"missing bundle file {entry.file}")
    digest = sha256_file(path)
    if digest != entry.sha256:
        raise IntegrityError(f"hash mismatch for {entry.file}")

    from git_vault.crypto import decrypt

    plaintext = decrypt(key, path.read_bytes())
    with tempfile.TemporaryDirectory(prefix="git-vault-") as tmp:
        raw = Path(tmp) / "bundle"
        raw.write_bytes(plaintext)
        # Verify bundle lists HEAD or tip
        gitops.fetch_bundle(ws.root, raw, f"HEAD:{INCOMING_REF}")
        # First bundle on empty repo: may need checkout
        local_head = gitops.rev_parse(ws.root, "HEAD")
        if local_head is None:
            gitops.run_git("checkout", "-B", "main", INCOMING_REF, cwd=ws.root)
        else:
            if entry.from_rev and local_head != entry.from_rev:
                # Allow if local is exactly at from_rev; otherwise conflict
                if not gitops.is_ancestor(ws.root, entry.from_rev, "HEAD") and local_head != entry.from_rev:
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
            # Bundle tip should match; after FF we expect entry.to
            if tip != entry.to:
                # Still OK if objects present — force branch to declared tip if ancestor
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
    key = resolve_repo_key(ws)
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


def cmd_clone(remote_url: str, directory: Path | None) -> Path:
    # Probe vault.json via cache clone
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

    import json

    meta = json.loads(vault_json.read_text(encoding="utf-8"))
    repo_id = str(meta["repo_id"])

    dest = (directory or Path.cwd() / Path(repo_id).name).resolve()
    if dest.exists() and any(dest.iterdir()):
        raise WorkspaceError(f"destination not empty: {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    gitops.init_repo(dest, bare=False)

    key = _repo_key_for(repo_id)
    manifest = load_manifest(cache, key)
    ws = write_workspace(dest, repo_id=repo_id, remote=remote_url, last_seq=0)

    if not manifest.bundles:
        return dest

    for entry in manifest.bundles:
        _apply_bundle(ws, cache, entry, key)
        ws.set_last_seq(entry.seq)

    return dest


def cmd_export_key(out: Path, cwd: Path | None = None) -> None:
    ws = find_workspace(cwd)
    key = resolve_repo_key(ws)
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
