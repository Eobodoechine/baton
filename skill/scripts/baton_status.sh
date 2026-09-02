#!/usr/bin/env bash
# baton_status.sh — one portable JSON object describing Baton state.
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
repo_dir=$(cd "$script_dir/../.." && pwd -P)
base_dir=$(sed -n 's/^[[:space:]]*base_dir=//p' "$HOME/.baton-config" 2>/dev/null | tail -1 || true)
if [ -z "$base_dir" ]; then
  base_dir=$(sed -n 's/^[[:space:]]*base_dir=//p' "$HOME/.loop-team-config" 2>/dev/null | tail -1 || true)
fi
base_dir=${base_dir:-$repo_dir}
status_py="$base_dir/hooks/baton_status.py"

if [ ! -f "$status_py" ]; then
  printf '{"error":"baton status helper is missing","root":""}\n'
  exit 2
fi

exec python3 "$status_py"
