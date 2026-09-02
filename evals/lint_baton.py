#!/usr/bin/env python3
"""lint_baton.py — mechanical conformance check for a baton (loop-team/BATON_SPEC.md).

Checks only what can be checked mechanically. It cannot tell you whether the baton is
TRUE — that is what the receiver eval is for. Usage:

    lint_baton.py path/to/BATON.md [--tier brief|teaching]

Exit 0 = conforms. Exit 1 = spec violations. Exit 2 = input error.
Exit 3 = internal error (no verdict reached).
"""
import argparse
import os
import re
import sys
import traceback

EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_INPUT_ERROR = 2
EXIT_INTERNAL_ERROR = 3

MANDATORY = [
    "## 1. DO THIS NOW",
    "## 2. WHERE YOU ARE",
    "## 3. THE TASK",
    "## 4. DO NOT RETRY",
    "## 5. USER'S WORDS",
    "## 6. RULES THAT BIND THIS TASK",
    "## 11. DONE MEANS",
]
PLACEHOLDER = re.compile(r"\{\{[\w|-]+\}\}|<fill in>|TODO\b|TBD\b")
# Tiers are DETAIL budgets, not model classes. The old model-named values are kept as
# aliases so existing batons keep linting, but a tier never selects a model -- the relay
# inherits the configured one (scripts/baton_next.sh).
CANON = {"brief": "brief", "teaching": "teaching",
         "haiku": "brief", "frontier": "teaching"}
CAPS = {"brief": 2500, "teaching": 5000}


def strip_comments(body):
    return re.sub(r"<!--.*?-->", "", body, flags=re.S)


def headings(body):
    """Return real markdown section headings and bodies, excluding fenced examples."""
    lines = strip_comments(body).split("\n")
    marks = []
    fenced = False
    for index, line in enumerate(lines):
        if re.match(r"\s*(?:```|~~~)", line):
            fenced = not fenced
            continue
        if not fenced and line.startswith("##"):
            marks.append((index, line.strip()))
    result = []
    for pos, (index, heading) in enumerate(marks):
        end = marks[pos + 1][0] if pos + 1 < len(marks) else len(lines)
        result.append((heading, "\n".join(lines[index + 1:end])))
    return result


def heading_is(heading, required):
    if not heading.startswith(required):
        return False
    rest = heading[len(required):]
    return not rest or not rest[0].isalnum()


def section_body(body, header):
    for heading, text in headings(body):
        if heading_is(heading, header):
            return text
    return None


def section(body, header):
    for heading, text in headings(body):
        if heading_is(heading, header):
            return heading + "\n" + text
    return ""


def header_region(body):
    lines = strip_comments(body).split("\n")
    keep = []
    fenced = False
    for line in lines:
        if re.match(r"\s*(?:```|~~~)", line):
            fenced = not fenced
            continue
        if not fenced and line.startswith("##"):
            break
        if not fenced:
            keep.append(line)
    return "\n".join(keep)


def check(path, tier, repo_root=None):
    body = open(path, encoding="utf-8", errors="replace").read()
    bad = []

    for h in MANDATORY:
        rest = section_body(body, h)
        if rest is None:
            bad.append("missing mandatory section: %s" % h)
        elif not rest.strip():
            bad.append("section is present but empty: %s — write content or 'none'"
                       % h)

    nums = [int(match.group(1)) for match in
            (re.match(r"##\s*(\d+)\.", h) for h, _ in headings(body)) if match]
    out_of_order = [b for a, b in zip(nums, nums[1:]) if b <= a]
    if out_of_order:
        bad.append("sections are out of order at section %s"
                   % ", ".join(str(number) for number in out_of_order))

    for m in PLACEHOLDER.finditer(body):
        bad.append("unfilled placeholder: %s" % m.group(0))

    # Token estimate. ~4 chars/token is the standard rough ratio; this is a guard
    # rail, not an accounting tool.
    est = len(body) // 4
    cap = CAPS[tier]
    if est > cap:
        bad.append("over budget: ~%d tokens estimated, cap is %d for tier %s"
                   % (est, cap, tier))

    steps = re.findall(r"^\s*(\d+)\.\s", section(body, "## 3. THE TASK"), re.M)
    if tier == "brief" and len(steps) > 10:
        bad.append("section 3 has %d numbered steps; brief tier allows 10 "
                   "(cut a smaller baton instead)" % len(steps))
    if not steps:
        bad.append("section 3 has no numbered steps")

    rules = [l for l in section(body, "## 6. RULES THAT BIND").splitlines()
             if l.strip().startswith("- ")]
    if len(rules) > 5:
        bad.append("section 6 has %d rules; at most 5 may bind one task "
                   "(the rest belong in PROJECT_CARD.md)" % len(rules))

    # Primacy/recency: the one action must occupy both privileged positions.
    s1 = section(body, "## 1. DO THIS NOW")
    m = re.search(r"^Run:\s*(.+)$", s1, re.M)
    if not m:
        bad.append("section 1 has no 'Run:' line")
    else:
        cmd = " ".join(m.group(1).split())
        tail = " ".join(section(body, "## 11. DONE MEANS").split())
        if cmd not in tail:
            bad.append("section 11 does not repeat section 1's command verbatim")

    head = header_region(body)
    if "Trust rule:" not in head:
        bad.append("header is missing the Trust rule line")
    if not re.search(r"^Card:.*@\s*[0-9a-f]{8}", head, re.M):
        bad.append("header is missing a 'Card: <path> @ <hash8>' pin")
    repo = re.search(r"^Repo:(.*)$", head, re.M)
    if not repo:
        bad.append("header is missing the 'Repo:' line")
    elif not os.path.isabs(repo.group(1).strip()):
        bad.append("header 'Repo:' line must name an absolute repository path")
    elif repo_root and os.path.realpath(repo.group(1).strip()) != os.path.realpath(repo_root):
        bad.append("header 'Repo:' does not match the repository being relayed")

    version = re.search(r"^Baton-Version:\s*(\S+)\s*$", head, re.M)
    if version and version.group(1) not in ("1", "2"):
        bad.append("unsupported Baton-Version: %s" % version.group(1))
    if version and version.group(1) == "2":
        head_sha = re.search(r"^Head:\s*([0-9a-f]{40})\s*$", head, re.M)
        worktree = re.search(r"^Worktree:\s*(clean|dirty)\s*$", head, re.M)
        fingerprint = re.search(r"^Worktree-Fingerprint:\s*sha256:[0-9a-f]{64}\s*$", head, re.M)
        if not head_sha:
            bad.append("version-2 baton is missing a 40-character Head")
        if not worktree:
            bad.append("version-2 baton is missing Worktree: clean|dirty")
        if not fingerprint:
            bad.append("version-2 baton is missing a SHA-256 Worktree-Fingerprint")

    s5 = section(body, "## 5. USER'S WORDS")
    if '"' not in s5 and "none recorded" not in s5:
        bad.append("section 5 must hold a verbatim quote or the exact words "
                   "'none recorded' — paraphrase is forbidden")

    if re.search(r"verdict:\s*pass", body, re.I):
        bad.append("contains the pass-verdict shape loop_stop_guard.py matches on; "
                   "write 'Verifier result — green' instead")

    if tier == "brief" and "## 10. DECISIONS" in body:
        bad.append("section 10 is teaching-tier only")

    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("baton")
    ap.add_argument("--tier", choices=sorted(CANON), default=None)
    ap.add_argument("--repo-root", default=None)
    a = ap.parse_args()

    if not os.path.exists(a.baton):
        print("INPUT ERROR: no such baton: %s" % a.baton, file=sys.stderr)
        return EXIT_INPUT_ERROR
    if os.path.isdir(a.baton):
        print("INPUT ERROR: not a file: %s" % a.baton, file=sys.stderr)
        return EXIT_INPUT_ERROR
    try:
        head = open(a.baton, encoding="utf-8", errors="replace").read(2000)
    except OSError as exc:
        print("INPUT ERROR: cannot read %s: %s" % (a.baton, exc), file=sys.stderr)
        return EXIT_INPUT_ERROR

    tier = a.tier
    if tier is None:
        # "Detail tier:" is current; "Receiver tier:" is the pre-rename header.
        m = re.search(r"^(?:Detail|Receiver) tier:\s*(\w+)", head, re.M)
        tier = m.group(1) if m and m.group(1) in CANON else "teaching"

    tier = CANON.get(tier, "teaching")
    bad = check(a.baton, tier, repo_root=a.repo_root)
    if not re.search(r"^Baton-Version:\s*2\s*$", head, re.M):
        print("WARNING: legacy version-1 baton: worktree fingerprint unavailable", file=sys.stderr)
    for b in bad:
        print("FAIL: %s" % b)
    if not bad:
        print("OK: %s conforms (tier %s)" % (a.baton, tier))
    return EXIT_VIOLATIONS if bad else EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        print("INTERNAL ERROR: lint_baton.py reached no verdict", file=sys.stderr)
        sys.exit(EXIT_INTERNAL_ERROR)
