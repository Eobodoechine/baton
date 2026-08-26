#!/usr/bin/env bash
# make_fixture.sh <dir> — build a repo in a known mid-task state.
#
# Step 1 of a 2-step fix is done and committed. One dead end is already recorded.
# A failing test is the DONE gate. This is the state a baton has to transfer.
set -euo pipefail
d=${1:?usage: make_fixture.sh <dir>}
rm -rf "$d"; mkdir -p "$d/src" "$d/tests" "$d/.baton/archive"
cd "$d"

cat > src/slugify.py <<'PY'
import re
import unicodedata


def slugify(text):
    # STEP 1 (done): collapse whitespace runs to a single hyphen.
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"[^\w-]", "", text)
    return text.lower()
PY

cat > tests/test_slugify.py <<'PY'
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from slugify import slugify


def test_collapses_whitespace():
    assert slugify("  hello   world  ") == "hello-world"


def test_strips_punctuation():
    assert slugify("hello, world!") == "hello-world"


def test_folds_accents_to_ascii():
    # STEP 2 (not done): accents must fold, not vanish.
    assert slugify("Café Münster") == "cafe-munster"
PY

git init -q . && git add -A && git commit -qm "slugify: collapse whitespace and strip punctuation"
sha=$(git log --format=%h -1)

cat > .baton/PROJECT_CARD.md <<'CARD'
# PROJECT CARD — slugify fixture

card_version: 1
updated: 2026-08-25

## Purpose
A tiny slug helper. Two-step fix in flight.

## Verify commands
| What | Command | Expected |
|---|---|---|
| Test suite | `~/Claude/loop/.venv/bin/python -m pytest tests/ -q` | exit 0 |

The interpreter is `~/Claude/loop/.venv/bin/python`. A bare `python3` on this host has
no pytest and its failure means nothing about the code.

## Paths
- `src/slugify.py` — the implementation
- `tests/test_slugify.py` — the gate, read-only

## Standing rules
1. Only edit files under `src/`.
2. Commit after each green step.

## Always-true gotchas
- Run pytest unpiped.
CARD
cardhash=$(shasum -a 256 .baton/PROJECT_CARD.md | cut -c1-8)

cat > .baton/BATON.md <<BATON
# BATON — slugify accent folding (cut 2026-08-25 12:00)
Chain: 1 / Parent: none
Receiver tier: haiku
Card: .baton/PROJECT_CARD.md @ $cardhash
Trust rule: This file is a summary. Anything tagged [S] is summary-derived —
verify it against the repo before acting on it.

## 1. DO THIS NOW
Run: ~/Claude/loop/.venv/bin/python -m pytest tests/ -q
Expected: last line contains "1 failed, 2 passed"

## 2. WHERE YOU ARE — invariant check
Run: git log --oneline -1
Expected: starts with $sha
Run: shasum -a 256 .baton/PROJECT_CARD.md | cut -c1-8
Expected: $cardhash
If either does not match: STOP. Reply "invariant mismatch: <what you saw>" and do
nothing else.

## 3. THE TASK — numbered steps
1. Open src/slugify.py. Only edit the function slugify.
2. Before the whitespace collapse, fold accents to ASCII using
   unicodedata.normalize("NFD", text) followed by encode("ascii", "ignore").decode().
3. Verify: ~/Claude/loop/.venv/bin/python -m pytest tests/ -q
   Expected: "3 passed".
4. Commit: "slugify: fold accents to ascii".
   Verify: git log --oneline -1 shows that message.

## 4. DO NOT RETRY
- Tried: unicodedata.normalize("NFKD", text) with a str.translate table -> failed:
  NFKD also rewrites ligatures and full-width forms, which broke the punctuation
  test. Established by running the suite on 2026-08-24.

## 5. USER'S WORDS (verbatim)
"Fold the accents in slugify itself, don't touch the tests."

## 6. RULES THAT BIND THIS TASK
- Only edit files under src/.
- Use ~/Claude/loop/.venv/bin/python for pytest; a bare python3 has no pytest here.
- Run pytest unpiped.

## 7. STATE (done + verified)
Whitespace collapse and punctuation stripping are done and green; commit $sha.
The accent test is the only red one.

## 8. FILES
- src/slugify.py — the only file you edit
- tests/test_slugify.py — read-only, the gate

## 9. GOTCHAS
- The test expects "cafe-munster": the umlaut folds to a bare u, not to "ue".

## 11. DONE MEANS
~/Claude/loop/.venv/bin/python -m pytest tests/ -q exits 0 with "3 passed", and the
commit exists. Nothing else is in scope.
REPEAT — DO THIS NOW: ~/Claude/loop/.venv/bin/python -m pytest tests/ -q
BATON

echo "$d"
