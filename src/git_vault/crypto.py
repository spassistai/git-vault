"""Password → repo_key derivation and AES-GCM encrypt/decrypt."""

from __future__ import annotations

import os
import secrets
from getpass import getpass

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from git_vault.paths import salt_path

MAGIC = b"GVAULT1\0"
NONCE_LEN = 12
REPO_KEY_LEN = 32
SALT_LEN = 16

# ~0.5–1s on typical laptop; set GIT_VAULT_FAST_KDF=1 for tests
ARGON2_TIME = 1 if os.environ.get("GIT_VAULT_FAST_KDF") == "1" else 3
ARGON2_MEMORY_KIB = 8 * 1024 if os.environ.get("GIT_VAULT_FAST_KDF") == "1" else 64 * 1024
ARGON2_PARALLELISM = 1 if os.environ.get("GIT_VAULT_FAST_KDF") == "1" else 4


class AuthError(Exception):
    """Missing or invalid credentials / ciphertext."""


def ensure_salt() -> bytes:
    path = salt_path()
    if path.exists():
        data = path.read_bytes()
        if len(data) != SALT_LEN:
            raise AuthError(f"corrupt salt file: {path}")
        return data
    data = secrets.token_bytes(SALT_LEN)
    path.write_bytes(data)
    path.chmod(0o600)
    return data


def get_master_password(prompt: str = "git-vault master password: ") -> str:
    env = os.environ.get("GIT_VAULT_PASSWORD")
    if env is not None and env != "":
        return env
    if not os.isatty(0):
        raise AuthError(
            "no password: set GIT_VAULT_PASSWORD or run in a TTY to prompt"
        )
    password = getpass(prompt)
    if not password:
        raise AuthError("empty password")
    return password


def derive_master_key(password: str, salt: bytes | None = None) -> bytes:
    if salt is None:
        salt = ensure_salt()
    kdf = Argon2id(
        salt=salt,
        length=REPO_KEY_LEN,
        iterations=ARGON2_TIME,
        lanes=ARGON2_PARALLELISM,
        memory_cost=ARGON2_MEMORY_KIB,
        ad=None,
        secret=None,
    )
    return kdf.derive(password.encode("utf-8"))


def derive_repo_key(master_key: bytes, repo_id: str) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=REPO_KEY_LEN,
        salt=None,
        info=f"git-vault:v1:{repo_id}".encode("utf-8"),
    )
    return hkdf.derive(master_key)


def repo_key_from_password(password: str, repo_id: str) -> bytes:
    return derive_repo_key(derive_master_key(password), repo_id)


def encrypt(repo_key: bytes, plaintext: bytes) -> bytes:
    if len(repo_key) != REPO_KEY_LEN:
        raise AuthError("repo key must be 32 bytes")
    nonce = secrets.token_bytes(NONCE_LEN)
    aesgcm = AESGCM(repo_key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return MAGIC + nonce + ciphertext


def decrypt(repo_key: bytes, blob: bytes) -> bytes:
    if len(repo_key) != REPO_KEY_LEN:
        raise AuthError("repo key must be 32 bytes")
    if not blob.startswith(MAGIC):
        raise AuthError("not a git-vault ciphertext (bad magic)")
    body = blob[len(MAGIC) :]
    if len(body) < NONCE_LEN + 16:
        raise AuthError("ciphertext too short")
    nonce, ciphertext = body[:NONCE_LEN], body[NONCE_LEN:]
    aesgcm = AESGCM(repo_key)
    try:
        return aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as exc:  # InvalidTag, etc.
        raise AuthError("decryption failed (wrong key or corrupt data)") from exc


def export_vaultkey(repo_id: str, repo_key: bytes) -> bytes:
    """Plaintext share format: repo_id + hex key (chmod 600 at write site)."""
    return f"git-vault-key/1\n{repo_id}\n{repo_key.hex()}\n".encode()


def import_vaultkey(data: bytes) -> tuple[str, bytes]:
    text = data.decode("utf-8")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 3 or lines[0] != "git-vault-key/1":
        raise AuthError("invalid vaultkey file")
    repo_id = lines[1]
    try:
        key = bytes.fromhex(lines[2])
    except ValueError as exc:
        raise AuthError("invalid vaultkey hex") from exc
    if len(key) != REPO_KEY_LEN:
        raise AuthError("vaultkey has wrong length")
    return repo_id, key
