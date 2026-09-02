#!/usr/bin/env bash
# POSIX convenience wrapper. The installer itself is cross-platform Python.
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
python_bin=${BATON_PYTHON:-python3}
exec "$python_bin" "$repo_dir/install.py" "$@"
