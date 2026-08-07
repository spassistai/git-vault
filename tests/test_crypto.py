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
    get_master_password,
    import_vaultkey,
    new_salt,
    repo_key_from_password,
)


def test_encrypt_roundtrip() -> None:
    salt = new_salt()
    key = repo_key_from_password("secret", "github.com/u/r", salt)
    blob = encrypt(key, b"hello vault")
    assert decrypt(key, blob) == b"hello vault"


def test_wrong_key_fails() -> None:
    salt = new_salt()
    key = repo_key_from_password("secret", "repo-a", salt)
    other = repo_key_from_password("secret", "repo-b", salt)
    blob = encrypt(key, b"data")
    with pytest.raises(AuthError):
        decrypt(other, blob)


def test_per_repo_keys_differ() -> None:
    salt = b"0123456789abcdef"
    master = derive_master_key("pw", salt)
    assert derive_repo_key(master, "a") != derive_repo_key(master, "b")


def test_same_password_same_salt_portable() -> None:
    salt = b"0123456789abcdef"
    a = repo_key_from_password("pw", "repo", salt)
    b = repo_key_from_password("pw", "repo", salt)
    assert a == b


def test_vaultkey_roundtrip() -> None:
    key = b"\x11" * 32
    data = export_vaultkey("github.com/u/r", key)
    rid, got = import_vaultkey(data)
    assert rid == "github.com/u/r"
    assert got == key


def test_password_confirm_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_VAULT_PASSWORD", "one")
    monkeypatch.setenv("GIT_VAULT_PASSWORD_CONFIRM", "two")
    with pytest.raises(AuthError, match="do not match"):
        get_master_password(confirm=True)


def test_password_confirm_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_VAULT_PASSWORD", "same")
    monkeypatch.setenv("GIT_VAULT_PASSWORD_CONFIRM", "same")
    assert get_master_password(confirm=True) == "same"
