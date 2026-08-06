# git-vault

Incremental encrypted git sync: plaintext locally, append-only encrypted bundles on GitHub.

Design: [DESIGN.md](DESIGN.md)

Agent skills (install copies into personal skill dirs):

- Cursor → `skills/cursor/git-vault/` → `~/.cursor/skills/git-vault/`
- Claude Code → `skills/claude/git-vault/` → `~/.claude/skills/git-vault/`

## Status

Scaffold + design. CLI MVP not implemented yet.

## Planned CLI

```bash
git-vault init | clone | pull | push | status | export-key | unlock
```

## Layout (this repo)

```
DESIGN.md
README.md
skills/
  cursor/git-vault/SKILL.md
  claude/git-vault/SKILL.md
src/git_vault/          # CLI package (stubs)
```
