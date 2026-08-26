#!/usr/bin/env bash
# baton_status.sh — one JSON blob describing baton state. The skill branches on it.
set -uo pipefail

root=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [ -z "$root" ]; then
  probe=$PWD
  while [ "$probe" != "/" ]; do
    [ -f "$probe/CLAUDE.md" ] && { root=$probe; break; }
    probe=$(dirname "$probe")
  done
fi
root=${root:-$PWD}

bdir="$root/.baton"
card="$bdir/PROJECT_CARD.md"
baton="$bdir/BATON.md"
pointer="$bdir/BATON_CURRENT"

card_hash=""
[ -f "$card" ] && card_hash=$(shasum -a 256 "$card" | cut -c1-8)

pinned=""
[ -f "$baton" ] && pinned=$(grep -m1 '^Card:' "$baton" 2>/dev/null | awk -F'@ *' '{print $2}' | tr -d ' ')

age="null"
if [ -f "$baton" ]; then
  mtime=$(stat -f %m "$baton" 2>/dev/null || stat -c %Y "$baton" 2>/dev/null || echo 0)
  age=$(awk -v m="$mtime" 'BEGIN{printf "%.1f", (systime()-m)/3600}')
fi

filled=false
if [ -f "$baton" ]; then
  missing=0
  while IFS= read -r s; do
    grep -qF "$s" "$baton" || missing=1
  done <<'SECTIONS'
## 1. DO THIS NOW
## 2. WHERE YOU ARE
## 3. THE TASK
## 4. DO NOT RETRY
## 5. USER'S WORDS
## 6. RULES THAT BIND THIS TASK
## 11. DONE MEANS
SECTIONS
  grep -qE '\{\{[A-Z_]+\}\}' "$baton" && missing=1
  [ "$missing" -eq 0 ] && filled=true
fi

gatedir=${LOOP_GATE_DIR:-$HOME/.loop-gate}
due=false
ls "$gatedir"/*_baton_due >/dev/null 2>&1 && due=true

matches=false
[ -n "$card_hash" ] && [ "$card_hash" = "$pinned" ] && matches=true

printf '{"root":"%s","card":"%s","card_hash":"%s","card_pinned":"%s","card_hash_matches":%s,"current_baton":"%s","pointer":"%s","age_hours":%s,"mandatory_sections_filled":%s,"due_flag":%s}\n' \
  "$root" \
  "$([ -f "$card" ] && echo "$card")" \
  "$card_hash" "$pinned" "$matches" \
  "$([ -f "$baton" ] && echo "$baton")" \
  "$([ -f "$pointer" ] && cat "$pointer")" \
  "$age" "$filled" "$due"
