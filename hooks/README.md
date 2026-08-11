# git-vault Claude Code hook

A safety hook for [Claude Code](https://claude.com/claude-code) that blocks a
plain `git push` inside a git-vault workspace and points you at
`git-vault push` instead — so encrypted bundles go to the vault remote and
plaintext never leaks to a wrong `origin`.

It's a `PreToolUse` / `Bash` hook. When a Bash command is a plain `git push`
and the target directory (PWD or a `cd <dir>` in the command) has a
`.git-vault` marker, the hook denies the call. Everything else — `git-vault
push`, other git commands, work outside a vault — passes through untouched.

## Install (per developer)

1. Copy the guard script into your Claude config:

   ```bash
   mkdir -p ~/.claude/hooks
   cp hooks/git-vault-guard.sh ~/.claude/hooks/git-vault-guard.sh
   chmod +x ~/.claude/hooks/git-vault-guard.sh
   ```

2. Merge the hook into `~/.claude/settings.json`. The snippet lives in
   [`settings.snippet.json`](settings.snippet.json) — add its `hooks` block to
   your existing settings (don't overwrite the file; merge the `hooks` key). If
   you already have `hooks.PreToolUse`, append the entry to that array.

3. Open `/hooks` once in an interactive Claude Code session (or restart it) so
   the new config is picked up.

Requires `jq` on PATH (used to parse the tool-call JSON).

## Verify

```bash
cd /path/to/a/git-vault/workspace
echo '{"tool_input":{"command":"git push"}}' | bash ~/.claude/hooks/git-vault-guard.sh
```

Prints a JSON `deny` object inside a vault, nothing outside one.
