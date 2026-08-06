---
name: git-vault
description: >-
  Encrypts and syncs git repositories via git-vault CLI (append-only age
  bundles on GitHub). Use when the user asks to push, pull, clone, or sync a
  vault-managed repo; when a repo contains .git-vault/; or when they mention
  git-vault, encrypted git remote, or vault push/pull.
---

# git-vault

Private encrypted git sync for Claude Code. Local tree = plaintext. GitHub = encrypted bundles only. Remote sync **only** via `git-vault` CLI.

## When to use

- User says push/pull/sync/clone for a vault or „zaszyfrowane repo”
- Working directory has `.git-vault/`
- `git-vault status` succeeds

## When not to use

- Ordinary non-vault repos → normal `git push` / `git pull`
- User explicitly wants plaintext GitHub remote

## Hard rules

1. Vault remote sync → `git-vault push` | `pull` | `clone` only
2. Never `git push` / `git pull` / `git fetch` to the vault artifact remote
3. Local `git commit` / `status` / `diff` / `log` are allowed
4. Never solicit or echo the master-password in the conversation
5. Exit code 2 (auth) → user unlocks in their terminal/Keychain; you do not handle the secret

## Quick reference

```bash
git-vault status
git-vault pull
git-vault push
git-vault clone <remote-url> [dir]
git-vault init [--repo-id ID] [--remote URL]
git-vault export-key --out path.vaultkey
git-vault unlock --key-file path.vaultkey
```

| Exit | Meaning |
|------|---------|
| 0 | OK |
| 2 | Need password/key — stop, tell user |
| 3 | Conflict — pull / resolve, no force |
| 4 | Network |
| 5 | Integrity failure — stop |

## Push checklist

```
- [ ] Local changes committed (git commit) if user wants them synced
- [ ] git-vault pull (if multi-machine risk)
- [ ] git-vault push
- [ ] Report CLI result
```

## Pull checklist

```
- [ ] git-vault pull
- [ ] Optional: git log -5 --oneline
```

## Clone

Use `git-vault clone`, not bare `git clone`, when the remote is a vault artifact repo (`bundles/*.bundle.age`, `manifest.age`).

## Sharing

`export-key` shares **one repo key**. Never share or ask for the master-password. Recipient uses `unlock --key-file`.

## Do not

- Roll your own encrypt-then-git-push pipeline
- Force-push vault remotes
- Put `GIT_VAULT_PASSWORD=…` in shell commands visible in the transcript
- Commit `*.vaultkey` unless the user explicitly requests it
