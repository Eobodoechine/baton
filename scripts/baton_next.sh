#!/usr/bin/env bash
# baton_next.sh — start (or print) the successor session for a cut baton.
#
# Claude Code cannot spawn a session from inside its own process, but a hook or skill
# step is just a shell command, and that command can launch an external `claude`.
# `--spawn` does exactly that, into a detached tmux session.
# See loop-team/BATON_SPEC.md section 6.
#
#   baton_next.sh              print the command
#   baton_next.sh --exec       replace this process with it
#   baton_next.sh --headless   print the non-interactive (claude -p) form
#   baton_next.sh --spawn      start it now, detached, in tmux   <- the relay
#
# Relay controls (env):
#   BATON_RELAY_GEN              set by the spawner on the child; absent => human-started
#   BATON_RELAY_MAX_GEN          chain depth cap (default 5)
#   BATON_RELAY_PERMISSION_MODE  passed to --permission-mode if set (default: unset)
set -euo pipefail

root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
baton="$root/.baton/BATON.md"
pointer="$root/.baton/BATON_CURRENT"

[ -f "$pointer" ] && baton=$(cat "$pointer")

if [ ! -f "$baton" ]; then
  echo "no baton found at $baton — cut one first (/baton cut)" >&2
  exit 1
fi

tier=$(grep -m1 '^Receiver tier:' "$baton" 2>/dev/null | awk '{print $3}' || true)
case "${tier:-haiku}" in
  frontier) model="opus" ;;
  *)        model="claude-haiku-4-5" ;;
esac

prompt="Read $baton and execute it. Follow it exactly; do not expand scope."

case "${1:-}" in
  --exec)     exec claude --model "$model" "$prompt" ;;
  --headless) echo "claude -p --model $model \"$prompt\"" ;;
  --spawn)    ;;  # handled below
  *)          echo "claude --model $model \"$prompt\""; exit 0 ;;
esac

# ---------------------------------------------------------------------------
# --spawn: launch the successor as a detached tmux session.
# ---------------------------------------------------------------------------

command -v tmux >/dev/null 2>&1 || {
  echo "baton relay: tmux not found — falling back to printing the command" >&2
  echo "claude --model $model \"$prompt\""
  exit 4
}

# Depth cap. A human-started session has no BATON_RELAY_GEN, so it is generation 0
# and its child is 1. The cap is what stops a relay chain running forever unattended.
gen="${BATON_RELAY_GEN:-0}"
max="${BATON_RELAY_MAX_GEN:-5}"
case "$gen$max" in *[!0-9]*) echo "baton relay: BATON_RELAY_GEN/MAX_GEN must be integers" >&2; exit 2 ;; esac
next=$((gen + 1))

if [ "$next" -gt "$max" ]; then
  echo "baton relay: chain depth cap reached (generation $next > BATON_RELAY_MAX_GEN=$max)." >&2
  echo "baton relay: NOT spawning. Start it by hand if you want to continue:" >&2
  echo "claude --model $model \"$prompt\""
  exit 3
fi

# Refuse to relay a baton that is missing its load-bearing sections. The skill's
# linter is the real check; this is the last gate before an unattended session
# inherits a half-written document.
for section in '## 1. DO THIS NOW' '## 2. WHERE YOU ARE' '## 3. THE TASK' '## 11. DONE MEANS'; do
  grep -qF "$section" "$baton" || {
    echo "baton relay: '$baton' is missing '$section' — refusing to relay an incomplete baton." >&2
    exit 5
  }
done

# Claude Code records per-folder trust under the REALPATH form (/private/tmp/... on
# macOS, not /tmp/...). Launch the child under the same form so the two agree.
root_real=$(cd "$root" && pwd -P)

relay_dir="$root/.baton/relay"
mkdir -p "$relay_dir"

# Launchers and pane logs are debris, not artifacts — batons.log is the durable record.
# Prune anything older than a week so an armed project does not accumulate forever.
find "$relay_dir" -maxdepth 1 -type f \( -name 'launch-baton-*.sh' -o -name 'baton-*.log' \) \
  -mtime +7 -delete 2>/dev/null || true

slug=$(basename "$root" | tr -c 'A-Za-z0-9' '-' | sed 's/-\{1,\}/-/g; s/^-//; s/-$//')
session="baton-${slug:-project}-g${next}-$(date +%H%M%S)"
launcher="$relay_dir/launch-$session.sh"
log="$relay_dir/$session.log"

# The successor is told to run the invariant check first — the one behavior that
# makes a stale relay halt instead of acting on a state that no longer holds.
child_prompt="Pick up the baton. Read $baton and execute it.

Run the section 2 invariant check BEFORE touching anything. If it does not match, STOP
and report the mismatch — do not improvise around it. Then execute section 3 in order,
running each step's verify command. Do not do anything the baton does not ask for.

(Baton relay generation $next of $max. Cutting a baton at the end of this session will
spawn generation $((next + 1)); at $max the chain stops and waits for a human.)"

# A generated launcher, rather than passing the prompt through tmux's argv, keeps a
# multi-line prompt containing quotes from being re-split by a shell.
{
  printf '#!/usr/bin/env bash\n'
  printf 'export BATON_RELAY_GEN=%s\n' "$next"
  printf 'export BATON_RELAY_MAX_GEN=%s\n' "$max"
  printf 'cd %q || exit 1\n' "$root_real"
  printf 'exec claude --model %q' "$model"
  [ -n "${BATON_RELAY_PERMISSION_MODE:-}" ] && printf ' --permission-mode %q' "$BATON_RELAY_PERMISSION_MODE"
  printf ' %q\n' "$child_prompt"
} > "$launcher"
chmod +x "$launcher"

# Preflight. Neither of these blocks the spawn — the session starts fine, it just
# waits at a prompt. Both were caught by a live relay on 2026-08-26; say so up front
# rather than letting the user find a stalled pane an hour later.
warnings=""

trusted=$(python3 - "$root_real" <<'PYEOF' 2>/dev/null || echo unknown
import json, os, sys
try:
    d = json.load(open(os.path.expanduser("~/.claude.json")))
except Exception:
    print("unknown"); raise SystemExit
p = d.get("projects", {}).get(sys.argv[1], {})
print("yes" if p.get("hasTrustDialogAccepted") is True else "no")
PYEOF
)
if [ "$trusted" = "no" ]; then
  warnings="$warnings
  ! FOLDER NOT YET TRUSTED — the successor will stop at Claude Code's \"Is this a
    project you trust?\" prompt before it reads the baton. Attach once and press
    Enter; this folder never asks again. (Trust is per-folder, and running claude
    from a parent directory does not trust this one.)"
fi

if [ -z "${BATON_RELAY_PERMISSION_MODE:-}" ]; then
  warnings="$warnings
  ! NO PERMISSION MODE — the successor will stop at the first Bash/Edit approval
    prompt and wait. For an unattended relay, set BATON_RELAY_PERMISSION_MODE
    (e.g. acceptEdits) before cutting. Leaving it unset is the safe default."
fi

if tmux has-session -t "=$session" 2>/dev/null; then
  echo "baton relay: tmux session '$session' already exists — not spawning a duplicate." >&2
  exit 6
fi

tmux new-session -d -s "$session" -c "$root_real" "$launcher"
tmux pipe-pane -o -t "$session" "cat >> $(printf '%q' "$log")" 2>/dev/null || true

printf '%s\trelay\tgen=%s/%s\tsession=%s\tbaton=%s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$next" "$max" "$session" "$baton" \
  >> "$root/.baton/batons.log"

cat <<EOF
baton relay: successor started.

  session    $session
  generation $next of $max
  model      $model
  cwd        $root
  baton      $baton
  log        $log

  watch it   tmux attach -t $session      (detach again with ctrl-b d)
  peek       tmux capture-pane -p -t $session | tail -40
  stop it    tmux kill-session -t $session
${warnings:+
WILL WAIT FOR YOU:$warnings
}
EOF
