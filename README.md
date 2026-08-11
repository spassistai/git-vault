# git-vault

Incremental encrypted git sync: plaintext locally, append-only encrypted bundles on a git remote (e.g. GitHub).

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Password: set `GIT_VAULT_PASSWORD` (and `GIT_VAULT_PASSWORD_CONFIRM` for `init`) or enter it at the TTY prompt.

## Usage

```bash
# In an existing git project:
git-vault init --repo-id github.com/you/notes --remote git@github.com:you/notes-vault.git
# or local bare remote for testing:
git-vault init --repo-id demo --remote /tmp/notes-vault.git

git-vault push
git-vault pull
git-vault status
git-vault status --json

git-vault clone /tmp/notes-vault.git ~/code/notes
git-vault export-key --out notes.vaultkey   # share one repo, not master password
git-vault unlock --key-file notes.vaultkey
git-vault clone --key-file notes.vaultkey /tmp/notes-vault.git  # first clone without master password
```

## How it works

1. Derive `repo_key = HKDF(Argon2id(master_password, salt_from_vault.json), repo_id)`
2. On push: `git bundle` of new commits → AES-256-GCM → `bundles/NNNNNN.bundle.age` + encrypted manifest
3. On pull: decrypt new bundles → `git fetch` / FF merge

Local marker: `.git-vault/` (gitignored). Design details: [DESIGN.md](DESIGN.md).

## Agent skills

```bash
cp -R skills/cursor/git-vault ~/.cursor/skills/
mkdir -p ~/.claude/skills && cp -R skills/claude/git-vault ~/.claude/skills/
```

## Claude Code hook

A `PreToolUse` hook that blocks a plain `git push` inside a git-vault
workspace and redirects to `git-vault push`, so plaintext never leaks to a
wrong remote. Install per developer — see [hooks/README.md](hooks/README.md).

## Dev

```bash
pip install -e '.[dev]'
GIT_VAULT_FAST_KDF=1 pytest -q
```

## Status

MVP CLI implemented: `init`, `clone`, `push`, `pull`, `status`, `export-key`, `unlock`.
