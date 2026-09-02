#!/usr/bin/env python3
"""Regression tests for the portable Baton status command."""

import json
import os
import subprocess
import sys
import time

import pytest

HOOKS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HOOKS)
sys.path.insert(0, HOOKS)
import baton_gate as bg  # noqa: E402
import baton_status as status  # noqa: E402


def make_project(tmp_path, name="project"):
    root = tmp_path / name
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".baton" / "archive").mkdir(parents=True)
    return root


def valid_baton(root, path=None):
    path = path or root / ".baton" / "BATON.md"
    body = ["# BATON — status", "Repo: %s" % root,
            "Card: .baton/PROJECT_CARD.md @ deadbeef",
            "Trust rule: verify this file against the repository."]
    for heading in bg.MANDATORY_SECTIONS:
        body.append("%s\nreal content" % heading)
    path.write_text("\n\n".join(body) + "\n")
    return path


def test_status_uses_the_pointer_target_not_stale_baton_md(tmp_path):
    root = make_project(tmp_path)
    stale = valid_baton(root)
    old = time.time() - 8 * 3600
    os.utime(stale, (old, old))
    target = valid_baton(root, root / ".baton" / "archive" / "fresh.md")
    (root / ".baton" / "BATON_CURRENT").write_text(str(target))

    result = status.build_status(str(root), gate_dir=str(tmp_path / "gate"))

    assert result["current_baton"] == str(target)
    assert result["pointer_valid"] is True
    assert result["age_hours"] < 1


def test_status_reports_invalid_pointer_without_following_it(tmp_path):
    root = make_project(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("not a baton")
    (root / ".baton" / "BATON_CURRENT").write_text(str(outside))

    result = status.build_status(str(root), gate_dir=str(tmp_path / "gate"))

    assert result["current_baton"] == ""
    assert result["pointer_valid"] is False
    assert result["mandatory_sections_filled"] is False


def test_status_due_scope_is_explicit(tmp_path):
    root = make_project(tmp_path)
    gate = tmp_path / "gate"
    gate.mkdir()
    (gate / "other_baton_due").write_text("1 soft")
    (gate / "current_baton_due").write_text("1 soft")

    global_result = status.build_status(str(root), gate_dir=str(gate))
    session_result = status.build_status(
        str(root), gate_dir=str(gate), session_id="current")

    assert global_result["due_flag"] is True
    assert global_result["due_scope"] == "all_sessions"
    assert global_result["due_count"] == 2
    assert session_result["due_flag"] is True
    assert session_result["due_scope"] == "session"


def test_status_cli_is_valid_json_for_quoted_repository_path(tmp_path):
    name = "repo with spaces" if os.name == "nt" else 'repo "quoted"'
    root = make_project(tmp_path, name)
    valid_baton(root)
    env = dict(os.environ, HOME=str(tmp_path / "home"),
               USERPROFILE=str(tmp_path / "home"),
               LOOP_GATE_DIR=str(tmp_path / "gate"))
    os.makedirs(env["HOME"])

    run = subprocess.run(
        [sys.executable, os.path.join(ROOT, "hooks", "baton_status.py")],
        cwd=root, env=env, capture_output=True, text=True,
    )

    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["root"] == str(root)


def test_status_refuses_to_guess_a_root_outside_git(tmp_path):
    with pytest.raises(bg.BatonRootError):
        status.build_status(str(tmp_path), gate_dir=str(tmp_path / "gate"))
