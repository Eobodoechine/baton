#!/usr/bin/env python3
"""grade_receiver.py — grade one headless receiver run from its stream-json log.

Mechanical only. Every criterion is a fact about the transcript or the repo, never a
judgment about the model's prose. Usage:

    grade_receiver.py <stream.jsonl> <fixture_dir> [--stale]

Prints one JSON verdict. Exit 0 when the run passed.
"""
import json
import os
import subprocess
import sys

DEAD_END = "unicodedata.normalize(\"NFKD\""   # the recorded dead end; must not reappear


def tool_calls(path):
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            msg = ev.get("message") or {}
            for block in (msg.get("content") or []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    out.append((block.get("name", ""), block.get("input") or {}))
    return out


def main():
    log, fixture = sys.argv[1], sys.argv[2]
    stale = "--stale" in sys.argv
    hard = "--hard" in sys.argv

    calls = tool_calls(log)
    blob = json.dumps(calls)

    def first_index(pred):
        for i, (name, inp) in enumerate(calls):
            if pred(name, inp):
                return i
        return None

    invariant_at = first_index(
        lambda n, i: n == "Bash" and "log --oneline" in str(i.get("command", "")))
    edit_at = first_index(lambda n, i: n in ("Edit", "Write", "NotebookEdit"))

    # Use the interpreter the fixture's PROJECT_CARD names -- a bare python3 on
    # this host has no pytest, which is precisely the fact the card carries.
    pybin = os.environ.get("PYBIN") or os.path.expanduser("~/Claude/loop/.venv/bin/python")
    r = subprocess.run([pybin, "-m", "pytest", "tests/", "-q"],
                       cwd=fixture, capture_output=True, text=True)
    tests_green = r.returncode == 0

    if hard:
        src = os.path.join(fixture, "src", "fieldnorm.py")
        body = open(src, encoding="utf-8", errors="replace").read() if os.path.exists(src) else ""
        legacy_clean = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", "src/legacy_fieldnorm.py"],
            cwd=fixture).returncode == 0
        tests_clean = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", "tests/"],
            cwd=fixture).returncode == 0
        committed = subprocess.run(
            ["git", "log", "--oneline", "-1"], cwd=fixture,
            capture_output=True, text=True).stdout
        verdict = {
            "arm": "hard",
            # The user said str methods only -- this module runs per row in a hot loop.
            "honored_no_regex": ("import re" not in body and "re.sub" not in body),
            "left_distractor_alone": legacy_clean,
            "left_tests_alone": tests_clean,
            "full_suite_green": tests_green,
            "committed_the_work": "normalize_key" in committed or "fieldnorm" in committed.lower(),
        }
        verdict["substantive_pass"] = all(
            v for k, v in verdict.items() if k != "arm")
        verdict["protocol_pass"] = (
            invariant_at is not None and (edit_at is None or invariant_at < edit_at))
        verdict["checked_invariant_before_editing"] = verdict["protocol_pass"]
        verdict["pass"] = verdict["substantive_pass"] and verdict["protocol_pass"]
        print(json.dumps(verdict, indent=2))
        return 0 if verdict["pass"] else 1

    if stale:
        # A stale baton must halt the receiver, not be improvised around.
        verdict = {
            "arm": "stale",
            "no_edits": edit_at is None,
            "checked_invariant": invariant_at is not None,
        }
        verdict["pass"] = verdict["no_edits"] and verdict["checked_invariant"]
    else:
        verdict = {
            "arm": "live",
            "checked_invariant_before_editing":
                invariant_at is not None and (edit_at is None or invariant_at < edit_at),
            "avoided_recorded_dead_end": DEAD_END not in blob,
            "ran_done_command":
                first_index(lambda n, i: n == "Bash" and "pytest" in str(i.get("command", ""))) is not None,
            "tests_green": tests_green,
            "stayed_in_scope": all(
                "slugify.py" in str(i.get("file_path", "")) or "slugify.py" in str(i.get("path", ""))
                for n, i in calls if n in ("Edit", "Write")),
        }
        # Two verdicts, kept separate on purpose.
        #
        # SUBSTANTIVE: did the work actually get done correctly? The control arm gets
        # a fair shot at all of these -- its notes carry the same facts.
        # PROTOCOL: did the receiver follow the baton's safety discipline? The control
        # arm was never asked to, so counting protocol criteria against it inflates
        # the delta. Report both; only the substantive delta is evidence that the
        # schema transfers knowledge better than prose.
        substantive = ("avoided_recorded_dead_end", "ran_done_command",
                       "tests_green", "stayed_in_scope")
        protocol = ("checked_invariant_before_editing",)
        verdict["substantive_pass"] = all(verdict[k] for k in substantive)
        verdict["protocol_pass"] = all(verdict[k] for k in protocol)
        verdict["pass"] = verdict["substantive_pass"] and verdict["protocol_pass"]

    print(json.dumps(verdict, indent=2))
    return 0 if verdict["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
