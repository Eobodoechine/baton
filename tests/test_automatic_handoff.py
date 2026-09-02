"""Offline acceptance tests for Baton automatic handoff v1."""

import json
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "hooks"))
import baton_runtime as runtime  # noqa: E402
import baton_gate as gate  # noqa: E402


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True)


def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q")
    (root / "tracked.txt").write_text("initial\n")
    git(root, "add", "tracked.txt")
    git(root, "-c", "user.name=Baton Test", "-c", "user.email=baton@example.invalid",
        "commit", "-qm", "initial")
    (root / ".baton").mkdir()
    (root / ".baton" / "PROJECT_CARD.md").write_text("card version: 1\n")
    return root


def enable(monkeypatch, tmp_path, host="codex"):
    monkeypatch.setenv("BATON_HOME", str(tmp_path / "baton-home"))
    config = runtime.default_config(ROOT)
    config["auto_handoff"] = True
    config["agents"][host]["enabled"] = True
    runtime.write_config(config, write_legacy=False)


def valid_baton(root):
    state = runtime.worktree_state(str(root))
    card = runtime.file_hash(str(root / ".baton" / "PROJECT_CARD.md")).split(":", 1)[1][:8]
    body = """# BATON — automatic test
Baton-Version: 2
Detail tier: brief
Repo: {root}
Head: {head}
Worktree: {worktree}
Worktree-Fingerprint: {fingerprint}
Card: .baton/PROJECT_CARD.md @ {card}
Trust rule: verify this file against the repository.

## 1. DO THIS NOW
Run: python -m pytest
Expected: green

## 2. WHERE YOU ARE
Run: python scripts/batonctl.py verify-state
Expected: repository state verified

## 3. THE TASK
1. Do the work.

## 4. DO NOT RETRY
none

## 5. USER'S WORDS
none recorded

## 6. RULES THAT BIND THIS TASK
- Stay in scope.

## 11. DONE MEANS
python -m pytest exits zero. REPEAT: python -m pytest
""".format(root=root, card=card, **state)
    path = root / ".baton" / "BATON.md"
    path.write_text(body)
    return path


def test_codex_usage_does_not_double_count_cached_tokens(tmp_path):
    transcript = tmp_path / "codex.jsonl"
    transcript.write_text(json.dumps({
        "event_msg": {"token_count": {"info": {"context_window": 100_000,
            "last_token_usage": {"input_tokens": 70_000, "cached_input_tokens": 60_000}}}}
    }) + "\n")
    assert gate.codex_context_usage(str(transcript)) == (70_000, 100_000)


def test_claude_percentage_threshold_unavailable_data_and_stuck_detection(tmp_path, monkeypatch):
    root = project(tmp_path)
    enable(monkeypatch, tmp_path, host="claude")
    transcript = tmp_path / "claude.jsonl"
    transcript.write_text(json.dumps({"message": {"usage": {"input_tokens": 70}}}) + "\n")
    base = {"session_id": "claude", "cwd": str(root), "_baton_host": "claude",
            "transcript_path": str(transcript), "tool_name": "Read", "tool_input": {"x": 1}}
    # 70% is the explicit soft threshold; cache fields are counted only by Claude's
    # documented usage record parser.
    gate.mode_meter(dict(base, context_window=100))
    assert runtime.read_state("claude", "claude")["trigger_reason"] == "soft:70%"

    # No context window means no guessed threshold.  It becomes due only when the
    # independent stuck detector fires (or PreCompact later marks it).
    other = dict(base, session_id="unavailable", context_window=0)
    gate.mode_meter(other)
    assert runtime.read_state("claude", "unavailable")["phase"] == "observing"
    for _ in range(2):
        gate.mode_meter(other)
    assert runtime.read_state("claude", "unavailable")["trigger_reason"].startswith("stuck:")


def test_repeated_baton_state_verification_does_not_trigger_recursive_handoff(tmp_path, monkeypatch):
    root = project(tmp_path)
    enable(monkeypatch, tmp_path)
    payload = {
        "session_id": "receiver",
        "cwd": str(root),
        "_baton_host": "codex",
        "tool_name": "Bash",
        "tool_input": {
            "command": "python3 %s/scripts/batonctl.py verify-state --root %s --baton %s/.baton/BATON.md"
            % (root, root, root)
        },
    }
    for _ in range(gate.STUCK_REPEATS):
        gate.mode_meter(dict(payload))
    state = runtime.read_state("codex", "receiver")
    assert state["phase"] == "observing"
    assert state["recent"] == []


def test_claude_bash_description_does_not_hide_identical_command(tmp_path, monkeypatch):
    root = project(tmp_path)
    enable(monkeypatch, tmp_path, host="claude")
    for index in range(gate.STUCK_REPEATS):
        gate.mode_meter({
            "session_id": "claude-labels",
            "cwd": str(root),
            "_baton_host": "claude",
            "tool_name": "Bash",
            "tool_input": {"command": "pwd", "description": "call %d of 3" % (index + 1)},
        })
    state = runtime.read_state("claude", "claude-labels")
    assert state["phase"] == "due"
    assert state["trigger_reason"].startswith("stuck:")


def test_precompact_drives_due_stop_to_receipt_completion(tmp_path, monkeypatch, capsys):
    root = project(tmp_path)
    enable(monkeypatch, tmp_path)
    payload = {"session_id": "codex-session", "turn_id": "turn-1", "cwd": str(root),
               "_baton_host": "codex", "stop_hook_active": True}
    assert gate.mode_compact_marker(payload) == 0
    assert gate.mode_gate(payload) == 0
    continuation = json.loads(capsys.readouterr().out)
    assert continuation["decision"] == "block"
    assert "cut action" in continuation["reason"]

    baton = valid_baton(root)
    assert gate.mode_gate(payload) == 0
    continuation = json.loads(capsys.readouterr().out)
    assert continuation["decision"] == "block"
    assert "Do not rewrite the baton" in continuation["reason"]
    state = runtime.read_state("codex", "codex-session")
    info = gate._baton_launch_info(str(root), state, "codex")
    runtime.record_receipt(info["handoff_id"], "codex", "fake", task_id="task-123")
    assert gate.mode_gate(payload) == 0
    completed = runtime.read_state("codex", "codex-session")
    assert completed["phase"] == "launched"
    assert completed["stop_hook_active"] is True
    assert completed["receipt"]["task_id"] == "task-123"
    assert baton.exists()


def test_stop_caps_at_three_continuations_then_prints_manual_command(tmp_path, monkeypatch, capsys):
    root = project(tmp_path)
    enable(monkeypatch, tmp_path)
    payload = {"session_id": "limit", "cwd": str(root), "_baton_host": "codex"}
    gate.mode_compact_marker(payload)
    assert [gate.mode_gate(payload) for _ in range(4)] == [0, 0, 0, 0]
    state = runtime.read_state("codex", "limit")
    assert state["phase"] == "manual_required"
    output = capsys.readouterr().out
    assert output.count('"decision": "block"') == 3
    assert "baton_next.py --spawn --provider codex" in output


def test_project_override_suppresses_automatic_state(tmp_path, monkeypatch):
    root = project(tmp_path)
    enable(monkeypatch, tmp_path)
    (root / ".baton" / "AUTO_HANDOFF_DISABLED").write_text("off\n")
    gate.mode_compact_marker({"session_id": "off", "cwd": str(root),
                              "_baton_host": "codex"})
    assert runtime.read_state("codex", "off") == {}


def test_concurrent_duplicate_hooks_share_one_locked_state_transition(tmp_path, monkeypatch):
    root = project(tmp_path)
    enable(monkeypatch, tmp_path)
    payload = {"session_id": "parallel", "cwd": str(root), "_baton_host": "codex"}
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(lambda _i: gate.mode_compact_marker(payload), range(12))) == [0] * 12
    state = runtime.read_state("codex", "parallel")
    assert state["phase"] == "due"
    assert state["trigger_reason"] == "precompact:auto"
    assert len(list((Path(os.environ["BATON_HOME"]) / "state" / "codex").glob("parallel.json"))) == 1


@pytest.mark.parametrize("change", ["staged", "unstaged", "mixed", "untracked", "rename", "delete"])
def test_worktree_fingerprint_observes_git_state_and_excludes_baton(tmp_path, change):
    root = project(tmp_path)
    baseline = runtime.worktree_state(str(root))["fingerprint"]
    if change == "staged":
        (root / "tracked.txt").write_text("staged\n")
        git(root, "add", "tracked.txt")
    elif change == "unstaged":
        (root / "tracked.txt").write_text("unstaged\n")
    elif change == "mixed":
        (root / "tracked.txt").write_text("index\n")
        git(root, "add", "tracked.txt")
        (root / "tracked.txt").write_text("worktree\n")
    elif change == "untracked":
        (root / "new.txt").write_text("new\n")
    elif change == "rename":
        git(root, "mv", "tracked.txt", "renamed.txt")
    else:
        (root / "tracked.txt").unlink()
    assert runtime.worktree_state(str(root))["fingerprint"] != baseline


@pytest.mark.skipif(os.name == "nt", reason="symlink fixture is POSIX-only")
def test_worktree_fingerprint_observes_symlinks_and_ignores_baton(tmp_path):
    root = project(tmp_path)
    baseline = runtime.worktree_state(str(root))["fingerprint"]
    (root / "link").symlink_to("tracked.txt")
    assert runtime.worktree_state(str(root))["fingerprint"] != baseline
    (root / "link").unlink()
    (root / ".baton" / "BATON.md").write_text("volatile\n")
    assert runtime.worktree_state(str(root))["fingerprint"] == baseline


@pytest.mark.skipif(os.name == "nt", reason="local submodule fixture is POSIX-only")
def test_worktree_fingerprint_observes_submodule_status(tmp_path):
    child = tmp_path / "child"
    child.mkdir()
    git(child, "init", "-q")
    (child / "child.txt").write_text("one\n")
    git(child, "add", "child.txt")
    git(child, "-c", "user.name=Baton Test", "-c", "user.email=baton@example.invalid",
        "commit", "-qm", "child")
    root = project(tmp_path)
    git(root, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(child), "child")
    git(root, "add", ".gitmodules", "child")
    git(root, "-c", "user.name=Baton Test", "-c", "user.email=baton@example.invalid",
        "commit", "-qm", "submodule")
    baseline = runtime.worktree_state(str(root))["fingerprint"]
    (root / "child" / "child.txt").write_text("changed\n")
    assert runtime.worktree_state(str(root))["fingerprint"] != baseline


def test_changed_worktree_fails_closed_before_pickup(tmp_path, monkeypatch, capsys):
    root = project(tmp_path)
    baton = valid_baton(root)
    (root / ".baton" / "BATON_CURRENT").write_text(str(baton))
    (root / "tracked.txt").write_text("changed\n")
    monkeypatch.chdir(root)
    assert gate.mode_pickup({"session_id": "pickup"}) == 0
    assert (root / ".baton" / "BATON_CURRENT").exists()
    assert "mismatch" in capsys.readouterr().err
