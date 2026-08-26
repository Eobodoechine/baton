#!/usr/bin/env bash
# make_fixture_hard.sh <dir> — a fixture that can actually discriminate.
#
# The easy fixture failed to discriminate because one obvious change satisfied one
# obvious failing test. Haiku could recover everything it needed from the repo, so the
# baton had nothing to transfer.
#
# This one puts SIX facts in play that the repo does not state:
#   1. A verbatim user constraint (no regex in this module) that the obvious fix violates.
#   2. A distractor file that looks like the right place to edit.
#   3. A dead end that passes the visible test file and still leaves the suite red.
#   4. A second dead end that is subtly wrong on non-ASCII.
#   5. Scope: tests are read-only.
#   6. The interpreter gotcha (bare python3 has no pytest here).
#
# Both arms receive all six. The baton carries them as structure; the control arm
# carries them as prose. That is the honest comparison: same information, different
# presentation, and ~6 simultaneous instructions is exactly where p^n bites Haiku.
set -euo pipefail
d=${1:?usage: make_fixture_hard.sh <dir>}
rm -rf "$d"; mkdir -p "$d/src" "$d/tests" "$d/.baton/archive"
cd "$d"

cat > src/fieldnorm.py <<'PY'
"""Field normalizer. Called per-row in the ingest hot loop."""


def normalize_field(text):
    # Done: trim and collapse internal whitespace using str methods only.
    return " ".join(text.split())


def normalize_key(text):
    # NOT done: must lowercase, fold spaces to underscores, and drop any
    # character that is not a letter, digit or underscore.
    return text
PY

# The distractor: near-identical, deprecated, still imported elsewhere.
cat > src/legacy_fieldnorm.py <<'PY'
"""Deprecated. Retained for the v1 ingest path. Do not change behavior."""


def normalize_key(text):
    return text.lower().replace(" ", "_")
PY

cat > tests/test_fieldnorm.py <<'PY'
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from fieldnorm import normalize_key


def test_lowercases_and_underscores():
    assert normalize_key("First Name") == "first_name"


def test_drops_punctuation():
    assert normalize_key("Email (work)!") == "email_work"


def test_keeps_digits():
    assert normalize_key("Line 2") == "line_2"
PY

# Passing today. A regex-based fix that strips non-[a-z0-9_] breaks this one.
cat > tests/test_contract.py <<'PY'
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from fieldnorm import normalize_field


def test_field_normalizer_is_unchanged():
    assert normalize_field("  a   b  ") == "a b"


def test_unicode_letters_survive_key_normalization():
    from fieldnorm import normalize_key
    # Accented letters are letters. They must NOT be stripped.
    assert normalize_key("Prenom Elu") == "prenom_elu"
    assert normalize_key("Ubung Zwei") == "ubung_zwei"
PY

git init -q . && git add -A && git commit -qm "fieldnorm: normalize_field done, normalize_key pending"
sha=$(git log --format=%h -1)

cat > .baton/PROJECT_CARD.md <<'CARD'
# PROJECT CARD — fieldnorm fixture

card_version: 1
updated: 2026-08-25

## Purpose
Per-row field normalizer for the ingest path. `normalize_key` is mid-fix.

## Verify commands
| What | Command | Expected |
|---|---|---|
| Full suite | `~/Claude/loop/.venv/bin/python -m pytest tests/ -q` | exit 0 |

The interpreter is `~/Claude/loop/.venv/bin/python`. A bare `python3` on this host has
no pytest; its failure means nothing about the code.

## Paths
- `src/fieldnorm.py` — the live module
- `src/legacy_fieldnorm.py` — deprecated v1 path, behavior is frozen
- `tests/` — read-only

## Standing rules
1. Only edit `src/fieldnorm.py`.
2. Run the FULL suite before calling anything done, not just the failing file.
3. Commit after each green step.

## Always-true gotchas
- `src/fieldnorm.py` runs per row in a hot loop.
CARD
cardhash=$(shasum -a 256 .baton/PROJECT_CARD.md | cut -c1-8)

cat > .baton/BATON.md <<BATON
# BATON — fieldnorm normalize_key (cut 2026-08-25 12:00)
Chain: 1 / Parent: none
Receiver tier: haiku
Card: .baton/PROJECT_CARD.md @ $cardhash
Trust rule: This file is a summary. Anything tagged [S] is summary-derived —
verify it against the repo before acting on it.

## 1. DO THIS NOW
Run: ~/Claude/loop/.venv/bin/python -m pytest tests/ -q
Expected: last line contains "4 failed, 1 passed"

## 2. WHERE YOU ARE — invariant check
Run: git log --oneline -1
Expected: starts with $sha
Run: shasum -a 256 .baton/PROJECT_CARD.md | cut -c1-8
Expected: $cardhash
If either does not match: STOP. Reply "invariant mismatch: <what you saw>" and do
nothing else.

## 3. THE TASK — numbered steps
1. Open src/fieldnorm.py. Only edit the function normalize_key.
2. Lowercase the text, then replace each space with an underscore.
3. Keep only characters where ch.isalnum() or ch == "_", building the result with
   str methods and a comprehension. Use str.isalnum(), which keeps accented letters.
4. Verify: ~/Claude/loop/.venv/bin/python -m pytest tests/ -q
   Expected: "5 passed".
5. Commit: "fieldnorm: normalize_key lowercases, underscores and filters".
   Verify: git log --oneline -1 shows that message.

## 4. DO NOT RETRY
- Tried: re.sub(r"[^a-z0-9_]", "", key) -> failed: it makes all three tests in
  test_fieldnorm.py pass, so it LOOKS finished, but it strips accented letters and
  leaves the unicode assertion in tests/test_contract.py red -- 4 passed, 1 failed,
  not 5 passed. Established by running the full suite on 2026-08-24.
- Tried: editing src/legacy_fieldnorm.py because its normalize_key looked closer to
  correct -> failed: that module is the frozen v1 path and the tests do not import
  it. Nothing changed.

## 5. USER'S WORDS (verbatim)
"No regex in fieldnorm.py, it runs per row in the hot loop. str methods only. And
don't touch the tests."

## 6. RULES THAT BIND THIS TASK
- Only edit src/fieldnorm.py.
- Use str methods in this module; keep the regex module out of it.
- Run the FULL tests/ directory before calling it done, not just test_fieldnorm.py.
- Use ~/Claude/loop/.venv/bin/python for pytest; a bare python3 has no pytest here.

## 7. STATE (done + verified)
normalize_field is done and its contract test is green; commit $sha. normalize_key
is still a passthrough.

## 8. FILES
- src/fieldnorm.py — the only file you edit
- src/legacy_fieldnorm.py — frozen, do not edit
- tests/ — read-only, the gate

## 9. GOTCHAS
- str.isalnum() is true for accented letters; a byte-oriented [a-z0-9] filter is not.
  That difference is the whole trap here.

## 11. DONE MEANS
~/Claude/loop/.venv/bin/python -m pytest tests/ -q exits 0 with "5 passed", and the
commit exists. Nothing else is in scope.
REPEAT — DO THIS NOW: ~/Claude/loop/.venv/bin/python -m pytest tests/ -q
BATON

echo "$d"
