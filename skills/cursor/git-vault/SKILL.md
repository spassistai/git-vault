---
name: git-vault
description: >-
  Encrypts and syncs git repositories via git-vault CLI (append-only age
  bundles on GitHub). Use when the user asks to push, pull, clone, or sync a
  vault-managed repo; when a repo contains .git-vault/; or when they mention
  git-vault, encrypted git remote, or vault push/pull.
---

# git-vault

Private encrypted git sync. Local working tree is plaintext. GitHub stores only encrypted bundles. All remote sync goes through the `git-vault` CLI — never raw `git push` / `git pull` to the vault remote.

Full design: see project `git-vault/DESIGN.md` if present in the workspace; otherwise follow this skill only.

## Hard rules

1. If `.git-vault/` exists (or user says this is a vault repo):
   - **Remote sync:** only `git-vault push` / `git-vault pull` / `git-vault clone`
   - **Forbidden:** `git push`, `git pull`, `git fetch` against the vault artifact remote
2. Local git is fine: `status`, `diff`, `add`, `commit`, `log`, branch work
3. **Never** ask the user to paste the master-password into chat
4. **Never** put passwords in commands, env exports in the transcript, or commit messages
5. If `git-vault` needs a password and fails with exit 2, tell the user to unlock via Keychain / TTY — do not collect the password yourself

## Detect vault repo

```bash
test -d .git-vault && echo VAULT
# or
git-vault status
```

If `git-vault status` exits non-zero because CLI missing: say install/build `git-vault` first; do not invent a manual encrypt workflow.

## Commands

Run from the working tree (except `clone`).

```bash
git-vault status
git-vault pull
git-vault push
git-vault clone <remote-url> [dir]
git-vault init [--repo-id ID] [--remote URL]
git-vault export-key [--out path.vaultkey]    # share one repo, not master password
git-vault unlock --key-file path.vaultkey
```

### Exit codes

| Code | Meaning | Agent action |
|------|---------|--------------|
| 0 | OK / no-op | Continue |
| 2 | Auth / missing key | Ask user to unlock locally; stop |
| 3 | Conflict | `git-vault pull` then resolve; do not force |
| 4 | Network | Retry once or report |
| 5 | Corrupt bundle | Stop; report hash/integrity error |

## Workflows

### Push (user: „wypchnij”, „push vault”, „sync up”)

1. `git status` — commit local work first if needed (normal `git commit`)
2. `git-vault pull` if unsure machine is current
3. `git-vault push`
4. Report success / no-op / error from CLI

### Pull (user: „pobierz”, „pull vault”, „sync down”)

1. `git-vault pull`
2. Summarize new commits if visible via `git log`

### Clone

```bash
git-vault clone git@github.com:USER/REPO-vault.git [dir]
```

Do not `git clone` the artifact remote expecting source files.

### Share one repo (no master-password)

```bash
git-vault export-key --out /safe/path/repo.vaultkey
```

Tell the recipient to `git-vault clone …` then `git-vault unlock --key-file repo.vaultkey` (or documented equivalent). Never export or request the master-password.

## Anti-patterns

- Encrypting files ad-hoc with `age`/`gpg` instead of `git-vault`
- Force-pushing to the vault remote
- Committing plaintext secrets „because the remote is encrypted” without user intent
- Storing `*.vaultkey` inside the project tree unless the user asks
