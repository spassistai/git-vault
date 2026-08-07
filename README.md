# git-vault

Incremental encrypted git sync: plaintext locally, append-only encrypted bundles on a git remote (e.g. GitHub).

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Password: set `GIT_VAULT_PASSWORD` or enter it at the TTY prompt (Keychain later).

## Usage

```bash
# In an existing git project:
git-vault init --repo-id github.com/you/notes --remote git@github.com:you/notes-vault.git
# or local bare remote for testing:
git-vault init --repo-id demo --remote /tmp/notes-vault.git

git-vault push
git-vault pull
git-vault status

git-vault clone /tmp/notes-vault.git ~/code/notes
git-vault export-key --out notes.vaultkey   # share one repo, not master password
git-vault unlock --key-file notes.vaultkey
```

## How it works

1. Derive `repo_key = HKDF(Argon2id(master_password), repo_id)`
2. On push: `git bundle` of new commits → AES-256-GCM → `bundles/NNNNNN.bundle.age` + encrypted manifest
3. On pull: decrypt new bundles → `git fetch` / FF merge

Local marker: `.git-vault/` (gitignored). Design details: [DESIGN.md](DESIGN.md).

## Agent skills

```bash
cp -R skills/cursor/git-vault ~/.cursor/skills/
mkdir -p ~/.claude/skills && cp -R skills/claude/git-vault ~/.claude/skills/
```

## Dev

```bash
pip install -e '.[dev]'
GIT_VAULT_FAST_KDF=1 pytest -q
```

## Status

MVP CLI implemented: `init`, `clone`, `push`, `pull`, `status`, `export-key`, `unlock`.
