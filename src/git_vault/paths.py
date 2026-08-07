"""Filesystem paths for git-vault config and artifact cache."""

from __future__ import annotations

import hashlib
from pathlib import Path


def config_dir() -> Path:
    path = Path.home() / ".config" / "git-vault"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = Path.home() / ".cache" / "git-vault"
    path.mkdir(parents=True, exist_ok=True)
    return path


def salt_path() -> Path:
    return config_dir() / "salt"


def artifact_cache_path(remote: str) -> Path:
    digest = hashlib.sha256(remote.encode()).hexdigest()[:16]
    cache_dir().mkdir(parents=True, exist_ok=True)
    return cache_dir() / digest
