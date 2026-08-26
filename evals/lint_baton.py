#!/usr/bin/env python3
"""lint_baton.py — mechanical conformance check for a baton (loop-team/BATON_SPEC.md).

Checks only what can be checked mechanically. It cannot tell you whether the baton is
TRUE — that is what the receiver eval is for. Usage:

    lint_baton.py path/to/BATON.md [--tier haiku|frontier]

Exit 0 = conforms. Exit 1 = violations, printed one per line.
"""
import argparse
import os
import re
import sys

MANDATORY = [
    "## 1. DO THIS NOW",
    "## 2. WHERE YOU ARE",
    "## 3. THE TASK",
    "## 4. DO NOT RETRY",
    "## 5. USER'S WORDS",
    "## 6. RULES THAT BIND THIS TASK",
    "## 11. DONE MEANS",
]
PLACEHOLDER = re.compile(r"\{\{[A-Z_|a-z-]+\}\}|<fill in>|TODO:|TBD\b")
CAPS = {"haiku": 2500, "frontier": 5000}


def section(body, header):
    """Text between `header` and the next `## ` heading."""
    i = body.find(header)
    if i < 0:
        return ""
    j = body.find("\n## ", i + len(header))
    return body[i:j if j > 0 else len(body)]


def check(path, tier):
    body = open(path, encoding="utf-8", errors="replace").read()
    bad = []

    for h in MANDATORY:
        if h not in body:
            bad.append("missing mandatory section: %s" % h)

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
    if tier == "haiku" and len(steps) > 10:
        bad.append("section 3 has %d numbered steps; haiku tier allows 10 "
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

    if "Trust rule:" not in body:
        bad.append("header is missing the Trust rule line")
    if not re.search(r"^Card:.*@\s*[0-9a-f]{8}", body, re.M):
        bad.append("header is missing a 'Card: <path> @ <hash8>' pin")

    s5 = section(body, "## 5. USER'S WORDS")
    if '"' not in s5 and "none recorded" not in s5:
        bad.append("section 5 must hold a verbatim quote or the exact words "
                   "'none recorded' — paraphrase is forbidden")

    if re.search(r"verdict:\s*pass", body, re.I):
        bad.append("contains the pass-verdict shape loop_stop_guard.py matches on; "
                   "write 'Verifier result — green' instead")

    if tier == "haiku" and "## 10. DECISIONS" in body:
        bad.append("section 10 is frontier-tier only")

    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("baton")
    ap.add_argument("--tier", choices=sorted(CAPS), default=None)
    a = ap.parse_args()

    if not os.path.exists(a.baton):
        print("no such baton: %s" % a.baton)
        return 1

    tier = a.tier
    if tier is None:
        head = open(a.baton, encoding="utf-8", errors="replace").read(2000)
        m = re.search(r"^Receiver tier:\s*(\w+)", head, re.M)
        tier = m.group(1) if m and m.group(1) in CAPS else "haiku"

    bad = check(a.baton, tier)
    for b in bad:
        print("FAIL: %s" % b)
    if not bad:
        print("OK: %s conforms (tier %s)" % (a.baton, tier))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
