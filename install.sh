#!/usr/bin/env bash
# install.sh — link the baton skill into Claude Code and print the hook registration.
#
# Refuses to clobber an existing install. Nothing here writes to settings.json; the
# hook JSON is printed for you to paste, because a bad hook registration wedges tool
# calls and that is not a thing to do to someone's config unasked.
set -euo pipefail

REPO=$(cd "$(dirname "$0")" && pwd -P)
SKILLS="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
DEST="$SKILLS/baton"

mkdir -p "$SKILLS"

if [ -e "$DEST" ] || [ -L "$DEST" ]; then
  if [ "$(readlink "$DEST" 2>/dev/null || true)" = "$REPO/skill" ]; then
    echo "already installed: $DEST -> $REPO/skill"
  else
    echo "refusing to overwrite existing $DEST" >&2
    echo "it is not a link to this repo. Move it aside first if you want to replace it." >&2
    exit 1
  fi
else
  ln -s "$REPO/skill" "$DEST"
  echo "linked $DEST -> $REPO/skill"
fi

printf 'base_dir=%s\n' "$REPO" > "$HOME/.baton-config"
echo "wrote $HOME/.baton-config (base_dir=$REPO)"

cat <<JSON

Optional. The skill works fully by hand without these; they add context metering, a
due-baton nag, a Stop gate, and auto-pickup. Paste into ~/.claude/settings.json,
keeping the "if [ -f ... ]" guard — a bare registration wedges a tool call when the
file is absent (SPEC.md section 6).

  "PostToolUse":     [{"matcher":"","hooks":[{"type":"command","command":"if [ -f $REPO/hooks/baton_gate.py ]; then python3 $REPO/hooks/baton_gate.py --meter; fi","timeout":10}]}]
  "UserPromptSubmit":[{"matcher":"","hooks":[{"type":"command","command":"if [ -f $REPO/hooks/baton_gate.py ]; then python3 $REPO/hooks/baton_gate.py --nag; fi","timeout":10}]}]
  "Stop":            [{"hooks":[{"type":"command","command":"if [ -f $REPO/hooks/baton_gate.py ]; then python3 $REPO/hooks/baton_gate.py --gate; fi","timeout":10}]}]
  "SessionStart":    [{"matcher":"startup|resume","hooks":[{"type":"command","command":"if [ -f $REPO/hooks/baton_gate.py ]; then python3 $REPO/hooks/baton_gate.py --pickup; fi","timeout":5}]},
                      {"matcher":"compact","hooks":[{"type":"command","command":"if [ -f $REPO/hooks/baton_gate.py ]; then python3 $REPO/hooks/baton_gate.py --post-compact-warn; fi","timeout":5}]}]
  "PreCompact":      [{"matcher":"auto","hooks":[{"type":"command","command":"if [ -f $REPO/hooks/baton_gate.py ]; then python3 $REPO/hooks/baton_gate.py --compact-marker; fi","timeout":5}]}]

The relay needs tmux. Optional env: BATON_RELAY_MAX_GEN (default 5),
BATON_RELAY_PERMISSION_MODE (unset = successor waits at approval prompts).
JSON
