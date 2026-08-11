#!/usr/bin/env bash
# git-vault guard: block a plain `git push` inside a git-vault workspace.
#
# Wired as a Claude Code PreToolUse/Bash hook. Reads the tool-call JSON on
# stdin, and if the command is a plain `git push` AND the target directory is
# a git-vault workspace (has a .git-vault marker), it denies the tool call and
# tells the model to use `git-vault push` instead — so encrypted bundles go
# out, never plaintext to a wrong remote.
#
# The target directory is taken from PWD *and* from a leading `cd <dir>` in
# the command (the common `cd sub && git push` form), each checked up its
# ancestry. Anything else (git-vault push, other git commands, work outside a
# vault) passes through. Exit 0 with no output = allow.

cmd=$(jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$cmd" ] && exit 0

# Only care about a plain `git push` (not `git-vault push`, not `git pushx`).
echo "$cmd" | grep -Eq '(^|[;&|( ])git( +-[^ ]+| +-C +[^ ]+)* +push([ ]|$)' || exit 0

is_vault() {
  # true if $1 or any ancestor holds a .git-vault marker
  local d="$1"
  [ -z "$d" ] && return 1
  case "$d" in /*) ;; *) d="$PWD/$d" ;; esac
  while [ -n "$d" ] && [ "$d" != "/" ]; do
    [ -d "$d/.git-vault" ] && return 0
    d=$(dirname "$d")
  done
  [ -d "/.git-vault" ] && return 0
  return 1
}

deny() {
  printf '%s' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"git-vault workspace: run \"git-vault push\" instead of \"git push\" — a plain git push would send unencrypted data to the wrong remote."}}'
  exit 0
}

# 1) current directory
is_vault "$PWD" && deny

# 2) a `cd <dir>` target inside the command (handles `cd sub && git push`)
cd_target=$(echo "$cmd" | sed -nE 's/.*(^|[;&|]) *cd +([^ ;&|]+).*/\2/p' | head -n1 | sed "s/^[\"']//;s/[\"']$//")
[ -n "$cd_target" ] && is_vault "$cd_target" && deny

exit 0
