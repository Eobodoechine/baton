#!/usr/bin/env bash
# POSIX convenience wrapper. The relay implementation is platform-neutral Python.
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
python_bin=${BATON_PYTHON:-python3}
exec "$python_bin" "$script_dir/baton_next.py" "$@"
