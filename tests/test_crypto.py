"""Unit tests for crypto primitives."""

from __future__ import annotations

import os

import pytest

os.environ["GIT_VAULT_FAST_KDF"] = "1"

from git_vault.crypto import (  # noqa: E402
    AuthError,
    decrypt,
    derive_master_key,
    derive_repo_key,
    encrypt,
    export_vaultkey,
    import_vaultkey,
)


def test_encrypt_roundtrip() -> None:
    key = derive_repo_key(derive_master_key("secret", salt=b"0123456789abcdef"), "github.com/u/r")
    blob = encrypt(key, b"hello vault")
    assert decrypt(key, blob) == b"hello vault"


def test_wrong_key_fails() -> None:
    key = derive_repo_key(derive_master_key("secret", salt=b"0123456789abcdef"), "repo-a")
    other = derive_repo_key(derive_master_key("secret", salt=b"0123456789abcdef"), "repo-b")
    blob = encrypt(key, b"data")
    with pytest.raises(AuthError):
        decrypt(other, blob)


def test_per_repo_keys_differ() -> None:
    master = derive_master_key("pw", salt=b"0123456789abcdef")
    assert derive_repo_key(master, "a") != derive_repo_key(master, "b")


def test_vaultkey_roundtrip() -> None:
    key = b"\x11" * 32
    data = export_vaultkey("github.com/u/r", key)
    rid, got = import_vaultkey(data)
    assert rid == "github.com/u/r"
    assert got == key
