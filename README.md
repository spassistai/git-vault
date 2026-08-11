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

## Onboarding a teammate

Give a teammate access to one vault **without sharing your master password**.
You hand over three things: the tool (this repo), a per-repo key file, and the
vault remote URL. They never see the master password, and their own `git push`
is guarded so plaintext can't leak.

**You (owner) — once per teammate:**

1. Export the per-repo key from a working copy of the vault (this needs your
   master password, but only produces the derived repo key — not the password):

   ```bash
   git-vault export-key --out project.vaultkey
   ```

2. Send them, over a secure channel: `project.vaultkey` and the vault remote
   URL (e.g. `git@github.com:you/project.git`). For a private remote, also
   grant their GitHub account read/write.

**Teammate — once:**

1. Install the tool:

   ```bash
   git clone https://github.com/spassistai/git-vault.git
   cd git-vault && python3 -m venv .venv && source .venv/bin/activate && pip install -e .
   ```

2. Install the push guard hook (needs `jq`):

   ```bash
   mkdir -p ~/.claude/hooks
   cp hooks/git-vault-guard.sh ~/.claude/hooks/git-vault-guard.sh
   chmod +x ~/.claude/hooks/git-vault-guard.sh
   ```

   Merge the `hooks` block from [hooks/settings.snippet.json](hooks/settings.snippet.json)
   into `~/.claude/settings.json`, then open `/hooks` once (or restart Claude
   Code) to load it.

**Teammate — per vault:**

```bash
git-vault clone --key-file project.vaultkey git@github.com:you/project.git
```

This pulls the encrypted bundles and decrypts them locally — no master
password needed. The key is stored in the workspace, so later `git-vault
push` / `git-vault pull` just work. From then on a plain `git push` in that
workspace is blocked by the hook; use `git-vault push`.

Rotating access later (e.g. someone leaves): regenerate the vault under a new
key and re-issue a fresh `*.vaultkey`. Note that rotation protects *future*
pushes only — anyone who already copied the old encrypted repo with the old
key can still read the old history.

## Dev

```bash
pip install -e '.[dev]'
GIT_VAULT_FAST_KDF=1 pytest -q
```

## Status

MVP CLI implemented: `init`, `clone`, `push`, `pull`, `status`, `export-key`, `unlock`.
