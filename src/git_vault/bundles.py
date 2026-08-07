"""Manifest and vault.json models + encrypted I/O."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from git_vault.crypto import decrypt, encrypt

FORMAT = "git-vault/1"


@dataclass
class BundleEntry:
    seq: int
    file: str
    from_rev: str | None
    to: str
    sha256: str

    @staticmethod
    def from_dict(data: dict[str, Any]) -> BundleEntry:
        return BundleEntry(
            seq=int(data["seq"]),
            file=str(data["file"]),
            from_rev=data.get("from"),
            to=str(data["to"]),
            sha256=str(data["sha256"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "file": self.file,
            "from": self.from_rev,
            "to": self.to,
            "sha256": self.sha256,
        }


@dataclass
class Manifest:
    repo_id: str
    head: str | None = None
    bundles: list[BundleEntry] = field(default_factory=list)

    @staticmethod
    def empty(repo_id: str) -> Manifest:
        return Manifest(repo_id=repo_id, head=None, bundles=[])

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Manifest:
        bundles = [BundleEntry.from_dict(b) for b in data.get("bundles", [])]
        return Manifest(
            repo_id=str(data["repo_id"]),
            head=data.get("head"),
            bundles=bundles,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_id": self.repo_id,
            "head": self.head,
            "bundles": [b.to_dict() for b in self.bundles],
        }

    @property
    def bundle_count(self) -> int:
        return len(self.bundles)

    @property
    def last_seq(self) -> int:
        return self.bundles[-1].seq if self.bundles else 0


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_vault_json(artifact_root: Path, repo_id: str, bundle_count: int) -> None:
    data = {
        "format": FORMAT,
        "repo_id": repo_id,
        "bundle_count": bundle_count,
    }
    (artifact_root / "vault.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )


def read_vault_json(artifact_root: Path) -> dict[str, Any]:
    path = artifact_root / "vault.json"
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(artifact_root: Path, manifest: Manifest, repo_key: bytes) -> None:
    plaintext = json.dumps(manifest.to_dict(), indent=2).encode("utf-8")
    blob = encrypt(repo_key, plaintext)
    (artifact_root / "manifest.age").write_bytes(blob)
    write_vault_json(artifact_root, manifest.repo_id, manifest.bundle_count)


def load_manifest(artifact_root: Path, repo_key: bytes) -> Manifest:
    path = artifact_root / "manifest.age"
    if not path.exists():
        meta = read_vault_json(artifact_root)
        return Manifest.empty(str(meta["repo_id"]))
    plaintext = decrypt(repo_key, path.read_bytes())
    return Manifest.from_dict(json.loads(plaintext.decode("utf-8")))


def bundle_filename(seq: int) -> str:
    return f"bundles/{seq:06d}.bundle.age"
