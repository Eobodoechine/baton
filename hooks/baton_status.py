#!/usr/bin/env python3
"""Portable JSON status for the Baton skill.

All path handling and JSON encoding live in Python so the result is valid on both
macOS and Linux, including repositories whose names contain quotes or whitespace.
"""

import glob
import hashlib
import json
import os
import re
import sys
import time

import baton_gate
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
import baton_runtime as runtime  # noqa: E402


def _card_pin(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            body = fh.read(4096)
    except OSError:
        return ""
    match = re.search(r"^Card:.*@\s*([0-9a-f]{8})\s*$", body, re.M)
    return match.group(1) if match else ""


def _hash8(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:8]
    except OSError:
        return ""


def build_status(start=None, gate_dir=None, session_id=None):
    root = baton_gate.project_root(start)
    bdir = baton_gate.baton_dir(root)
    card = os.path.join(bdir, "PROJECT_CARD.md")
    pointer = os.path.join(bdir, "BATON_CURRENT")

    pointer_text = ""
    pointer_valid = False
    if os.path.isfile(pointer):
        try:
            with open(pointer, encoding="utf-8") as fh:
                pointer_text = fh.read().strip()
            baton = baton_gate.resolve_baton_pointer(root, require_valid=False)
            pointer_valid = baton_gate.baton_is_valid(baton, expected_root=root)
        except (OSError, baton_gate.BatonPointerError):
            baton = None
    else:
        candidate = os.path.join(bdir, "BATON.md")
        baton = candidate if os.path.isfile(candidate) else None

    card_hash = _hash8(card)
    pinned = _card_pin(baton) if baton else ""
    age = None
    if baton:
        try:
            age = round((time.time() - os.path.getmtime(baton)) / 3600.0, 1)
        except OSError:
            age = None

    config = runtime.load_config()
    auto_states = []
    for host in ("codex", "claude"):
        directory = runtime.runtime_home() / "state" / host
        if directory.is_dir():
            for state_file in directory.glob("*.json"):
                try:
                    state = json.loads(state_file.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if isinstance(state, dict):
                    auto_states.append(state)
    active_auto = [state for state in auto_states
                   if state.get("phase") in ("due", "cutting", "launch_pending")]
    # Retain the old Loop marker in status only for the temporary compatibility
    # period.  New hosted hooks never create it.
    gate_dir = os.path.expanduser(gate_dir or os.environ.get("LOOP_GATE_DIR", "~/.loop-gate"))
    due_files = glob.glob(os.path.join(gate_dir, "*_baton_due"))
    session_id = session_id or os.environ.get("CLAUDE_SESSION_ID")
    if session_id:
        legacy_due = os.path.exists(os.path.join(
            gate_dir, "%s_baton_due" % baton_gate._session_key(session_id)))
        auto_due = any(state.get("session_id") == runtime.session_key(session_id)
                       for state in active_auto)
        due = legacy_due or auto_due
        due_scope = "session"
    else:
        due = bool(due_files or active_auto)
        due_scope = "all_sessions" if due else "none"

    return {
        "root": root,
        "card": card if os.path.isfile(card) else "",
        "card_hash": card_hash,
        "card_pinned": pinned,
        "card_hash_matches": bool(card_hash and card_hash == pinned),
        "current_baton": baton or "",
        "pointer": pointer_text,
        "pointer_valid": pointer_valid if pointer_text else None,
        "age_hours": age,
        "mandatory_sections_filled": bool(
            baton and baton_gate.baton_is_valid(baton, expected_root=root)),
        "due_flag": due,
        "due_scope": due_scope,
        "due_count": len(due_files) + len(active_auto),
        "automatic_handoff": config["auto_handoff"],
        "agents": config["agents"],
        "automatic_states": [{key: state.get(key) for key in
                              ("host", "session_id", "phase", "handoff_id", "last_error")}
                             for state in active_auto],
    }


def main(argv=None):
    try:
        result = build_status()
    except baton_gate.BatonRootError as exc:
        print(json.dumps({"error": str(exc), "root": ""}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
