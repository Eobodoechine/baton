#!/usr/bin/env python3
"""Regression tests for baton_gate.py (loop-team/BATON_SPEC.md).

Fixtures are real-shaped: transcripts carry the usage fields Claude Code actually
emits, batons are written through the real template sections, gate dirs are temp dirs.

Detection markers are built dynamically — this file must never arm any guard by being
read, and must never contain the pass-verdict shape loop_stop_guard.py matches on."""
import json
import os
import subprocess
import sys
import time

import pytest

HOOKS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOOKS)
import baton_gate as bg  # noqa: E402

# Built dynamically so this file never contains the literal shape (see docstring).
PASS_VERDICT_SHAPE = "verdict:" + " " + "pass"


# --- fixtures ---------------------------------------------------------------

@pytest.fixture
def gate(tmp_path, monkeypatch):
    d = tmp_path / "gate"
    d.mkdir()
    monkeypatch.setenv("LOOP_GATE_DIR", str(d))
    return d


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".baton").mkdir()
    monkeypatch.chdir(root)
    return root


def transcript(tmp_path, **usage):
    p = tmp_path / "t.jsonl"
    rows = [
        {"type": "user", "message": {"role": "user", "content": "hi"}},
        {"type": "assistant", "message": {"role": "assistant", "usage": usage}},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return str(p)


def write_baton(root, complete=True):
    body = ["# BATON — test", "Repo: %s" % root,
            "Card: .baton/PROJECT_CARD.md @ deadbeef",
            "Trust rule: verify this file against the repository."]
    sections = list(bg.MANDATORY_SECTIONS)
    if not complete:
        sections = sections[:-1]
    for s in sections:
        body.append(s + "\nreal content here")
    p = root / ".baton" / "BATON.md"
    p.write_text("\n\n".join(body) + "\n")
    return p


def run(mode, payload, env=None):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run(
        [sys.executable, os.path.join(HOOKS, "baton_gate.py"), mode],
        input=json.dumps(payload), capture_output=True, text=True, env=e,
    )


# --- project identity -------------------------------------------------------

def test_project_root_resolves_from_a_nested_directory(project):
    nested = project / "a" / "b"
    nested.mkdir(parents=True)
    assert bg.project_root(str(nested)) == str(project)


def test_project_root_refuses_to_guess_outside_git(tmp_path):
    with pytest.raises(bg.BatonRootError):
        bg.project_root(str(tmp_path))


def test_linked_worktree_resolves_to_its_exact_checkout(tmp_path):
    owner = tmp_path / "owner"
    owner.mkdir()
    subprocess.run(["git", "init", "-q", str(owner)], check=True)
    (owner / "tracked").write_text("one")
    subprocess.run(["git", "-C", str(owner), "add", "tracked"], check=True)
    subprocess.run([
        "git", "-C", str(owner), "-c", "user.name=Baton Test",
        "-c", "user.email=baton@example.invalid", "commit", "-qm", "initial",
    ], check=True)
    worktree = tmp_path / "worktree"
    subprocess.run([
        "git", "-C", str(owner), "worktree", "add", "-q", "-b",
        "baton-test-worktree", str(worktree),
    ], check=True)
    assert bg.project_root(str(worktree)) == str(worktree)


# --- context measurement ----------------------------------------------------

def test_context_tokens_sums_only_window_occupying_fields(tmp_path):
    t = transcript(tmp_path, input_tokens=1000, cache_read_input_tokens=50_000,
                   cache_creation_input_tokens=4_000, output_tokens=9_999)
    # output_tokens does NOT occupy the context window and must be excluded.
    assert bg.context_tokens(t) == 55_000


def test_context_tokens_uses_newest_usage_record(tmp_path):
    p = tmp_path / "t.jsonl"
    rows = [
        {"type": "assistant", "message": {"usage": {"input_tokens": 10}}},
        {"type": "assistant", "message": {"usage": {"input_tokens": 90_000}}},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert bg.context_tokens(str(p)) == 90_000


def test_context_tokens_degrades_to_zero_not_to_a_guess(tmp_path):
    assert bg.context_tokens(None) == 0
    assert bg.context_tokens(str(tmp_path / "nope.jsonl")) == 0
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n{also not\n")
    assert bg.context_tokens(str(bad)) == 0


def test_context_tokens_tail_reads_a_large_transcript(tmp_path):
    p = tmp_path / "big.jsonl"
    filler = json.dumps({"type": "user", "message": {"content": "x" * 2000}})
    with open(p, "w") as fh:
        for _ in range(600):          # comfortably exceeds TAIL_BYTES
            fh.write(filler + "\n")
        fh.write(json.dumps(
            {"type": "assistant", "message": {"usage": {"input_tokens": 7_777}}}) + "\n")
    assert os.path.getsize(p) > bg.TAIL_BYTES
    assert bg.context_tokens(str(p)) == 7_777


# --- meter ------------------------------------------------------------------

@pytest.mark.parametrize("tokens,expect_due", [
    (100_000, False),
    (bg.SOFT_TRIGGER - 1, False),
    (bg.SOFT_TRIGGER, True),
    (bg.HARD_TRIGGER, True),
])
def test_meter_flags_at_thresholds(tmp_path, gate, tokens, expect_due):
    t = transcript(tmp_path, input_tokens=tokens)
    bg.mode_meter({"session_id": "s1", "transcript_path": t, "tool_name": "Read",
                   "tool_input": {"file_path": "/a"}})
    assert os.path.exists(gate / "s1_baton_due") is expect_due


def test_meter_records_which_trigger_fired(tmp_path, gate):
    bg.mode_meter({"session_id": "s2",
                   "transcript_path": transcript(tmp_path, input_tokens=bg.HARD_TRIGGER),
                   "tool_name": "Read", "tool_input": {}})
    assert "hard:" in (gate / "s2_baton_due").read_text()


def test_meter_flags_three_identical_tool_calls_as_stuck(tmp_path, gate):
    t = transcript(tmp_path, input_tokens=1000)
    payload = {"session_id": "s3", "transcript_path": t, "tool_name": "Bash",
               "tool_input": {"command": "pytest -q"}}
    for _ in range(bg.STUCK_REPEATS):
        bg.mode_meter(dict(payload))
    assert "stuck:" in (gate / "s3_baton_due").read_text()


def test_meter_ignores_repeated_baton_state_verification(tmp_path, gate):
    t = transcript(tmp_path, input_tokens=1000)
    payload = {
        "session_id": "receiver",
        "transcript_path": t,
        "tool_name": "Bash",
        "tool_input": {
            "command": "python3 /opt/baton/scripts/batonctl.py verify-state --root /repo --baton /repo/.baton/BATON.md"
        },
    }
    for _ in range(bg.STUCK_REPEATS):
        bg.mode_meter(dict(payload))
    assert not os.path.exists(gate / "receiver_baton_due")


def test_meter_ignores_bash_description_when_command_is_identical(tmp_path, gate):
    t = transcript(tmp_path, input_tokens=1000)
    for index in range(bg.STUCK_REPEATS):
        bg.mode_meter({
            "session_id": "claude-labels",
            "transcript_path": t,
            "tool_name": "Bash",
            "tool_input": {"command": "pwd", "description": "call %d of 3" % (index + 1)},
        })
    assert "stuck:" in (gate / "claude-labels_baton_due").read_text()


def test_meter_does_not_flag_varied_tool_calls(tmp_path, gate):
    t = transcript(tmp_path, input_tokens=1000)
    for i in range(6):
        bg.mode_meter({"session_id": "s4", "transcript_path": t, "tool_name": "Bash",
                       "tool_input": {"command": "ls %d" % i}})
    assert not os.path.exists(gate / "s4_baton_due")


def test_meter_is_silent(tmp_path, gate):
    r = run("--meter", {"session_id": "s5",
                        "transcript_path": transcript(tmp_path, input_tokens=200_000),
                        "tool_name": "Read", "tool_input": {}},
            env={"LOOP_GATE_DIR": str(gate)})
    assert r.returncode == 0
    assert r.stdout.strip() == ""


# --- baton validity ---------------------------------------------------------

def test_baton_needs_every_mandatory_section(project):
    p = write_baton(project, complete=False)
    assert bg.baton_is_valid(str(p)) is False


def test_baton_rejects_unfilled_placeholders(project):
    p = write_baton(project)
    p.write_text(p.read_text() + "\n{{NEXT_ACTION}}\n")
    assert bg.baton_is_valid(str(p)) is False


@pytest.mark.parametrize("placeholder", ["{{next_action}}", "TODO", "TBD"])
def test_baton_rejects_every_template_placeholder_form(project, placeholder):
    p = write_baton(project)
    p.write_text(p.read_text() + "\n%s\n" % placeholder)
    assert bg.baton_is_valid(str(p)) is False


def test_baton_rejects_a_mandatory_heading_only_quoted_in_a_fence(project):
    p = write_baton(project)
    body = p.read_text().replace(
        "## 4. DO NOT RETRY\nreal content here",
        "## 9. GOTCHAS\n```markdown\n## 4. DO NOT RETRY\n```",
    )
    p.write_text(body)
    assert bg.baton_is_valid(str(p)) is False


def test_baton_rejects_an_empty_mandatory_section(project):
    p = write_baton(project)
    p.write_text(p.read_text().replace(
        "## 4. DO NOT RETRY\nreal content here", "## 4. DO NOT RETRY"))
    assert bg.baton_is_valid(str(p)) is False


def test_complete_baton_is_valid(project):
    assert bg.baton_is_valid(str(write_baton(project)), expected_root=str(project)) is True


def test_baton_rejects_a_different_repository_identity(project, tmp_path):
    p = write_baton(project)
    p.write_text(p.read_text().replace("Repo: %s" % project,
                                       "Repo: %s" % tmp_path))
    assert bg.baton_is_valid(str(p), expected_root=str(project)) is False


# --- nag --------------------------------------------------------------------

def test_nag_speaks_once_when_due(project, gate, capsys):
    (gate / "s6_baton_due").write_text("%d soft:141k\n" % int(time.time()))
    bg.mode_nag({"session_id": "s6"})
    out = capsys.readouterr().out
    assert "BATON DUE" in out
    assert json.loads(out)["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"


def test_nag_silent_when_not_due(project, gate, capsys):
    bg.mode_nag({"session_id": "s7"})
    assert capsys.readouterr().out == ""


def test_nag_stops_once_a_baton_exists(project, gate, capsys):
    (gate / "s8_baton_due").write_text("%d soft:141k\n" % (time.time() - 60))
    write_baton(project)
    bg.mode_nag({"session_id": "s8"})
    assert capsys.readouterr().out == ""
    assert not (gate / "s8_baton_due").exists()


def test_cut_closes_due_cycle_without_immediately_rearming(project, gate, tmp_path):
    flagged = time.time() - 60
    (gate / "cycle_baton_due").write_text("%d soft:141k\n" % flagged)
    write_baton(project)

    assert bg.mode_gate({"session_id": "cycle"}) == 0
    assert not (gate / "cycle_baton_due").exists()
    assert (gate / "cycle_baton_ack").exists()

    bg.mode_meter({
        "session_id": "cycle",
        "transcript_path": transcript(tmp_path, input_tokens=bg.HARD_TRIGGER),
        "tool_name": "Read",
        "tool_input": {"file_path": "/after-cut"},
    })
    assert not (gate / "cycle_baton_due").exists()


# --- stop gate --------------------------------------------------------------

def test_gate_never_blocks_outside_an_armed_loop_run(project, gate):
    (gate / "s9_baton_due").write_text("%d hard:161k\n" % int(time.time()))
    assert bg.mode_gate({"session_id": "s9"}) == 0


def test_gate_blocks_an_armed_run_with_no_baton(project, gate):
    (gate / "sA_target").write_text("armed")
    (gate / "sA_baton_due").write_text("%d hard:161k\n" % int(time.time()))
    assert bg.mode_gate({"session_id": "sA"}) == 2


def test_gate_releases_after_three_strikes_and_records_the_miss(project, gate):
    (gate / "sB_target").write_text("armed")
    (gate / "sB_baton_due").write_text("%d hard:161k\n" % int(time.time()))
    codes = [bg.mode_gate({"session_id": "sB"}) for _ in range(bg.MAX_STRIKES + 1)]
    assert codes == [2] * bg.MAX_STRIKES + [0]
    assert os.path.exists(gate / "sB_BATON_MISSING")


def test_gate_passes_once_a_valid_baton_is_written(project, gate):
    (gate / "sC_target").write_text("armed")
    (gate / "sC_baton_due").write_text("%d hard:161k\n" % (time.time() - 60))
    write_baton(project)
    assert bg.mode_gate({"session_id": "sC"}) == 0


def test_gate_still_blocks_on_a_placeholder_baton(project, gate):
    (gate / "sD_target").write_text("armed")
    (gate / "sD_baton_due").write_text("%d hard:161k\n" % (time.time() - 60))
    p = write_baton(project)
    p.write_text(p.read_text() + "\n{{DONE_COMMAND}}\n")
    assert bg.mode_gate({"session_id": "sD"}) == 2


def test_gate_never_writes_baton_prose(project, gate):
    """The machinery may stamp, never summarize (claude-code#46602)."""
    (gate / "sE_target").write_text("armed")
    (gate / "sE_baton_due").write_text("%d hard:161k\n" % int(time.time()))
    bg.mode_gate({"session_id": "sE"})
    assert not os.path.exists(project / ".baton" / "BATON.md")


# --- pickup -----------------------------------------------------------------

def test_pickup_announces_then_consumes_the_pointer(project, capsys):
    b = write_baton(project)
    pointer = project / ".baton" / "BATON_CURRENT"
    pointer.write_text(str(b))
    original = b.read_bytes()
    bg.mode_pickup({"session_id": "sF"})
    assert "Active baton" in capsys.readouterr().out
    assert not pointer.exists()
    assert b.read_bytes() == original
    assert "pickup session=sF" in (project / ".baton" / "batons.log").read_text()

    bg.mode_pickup({"session_id": "sG"})     # second session: nothing left to pick up
    assert capsys.readouterr().out == ""


def test_pickup_ignores_a_stale_baton(project, capsys):
    b = write_baton(project)
    old = time.time() - bg.BATON_TTL_SECONDS - 60
    os.utime(b, (old, old))
    (project / ".baton" / "BATON_CURRENT").write_text(str(b))
    bg.mode_pickup({"session_id": "sH"})
    assert capsys.readouterr().out == ""


def test_pickup_line_stays_small(project, capsys):
    """SessionStart already carries three other handlers -- stay out of their way."""
    b = write_baton(project)
    (project / ".baton" / "BATON_CURRENT").write_text(str(b))
    bg.mode_pickup({"session_id": "sI"})
    ctx = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert len(ctx) <= 200
    assert "## 3. THE TASK" not in ctx      # the body never rides in additionalContext


def test_pickup_refuses_pointer_outside_the_repository(project, tmp_path, capsys):
    outside = tmp_path / "outside.md"
    outside.write_text(write_baton(project).read_text())
    before = outside.read_bytes()
    pointer = project / ".baton" / "BATON_CURRENT"
    pointer.write_text(str(outside))

    bg.mode_pickup({"session_id": "outside"})

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "outside" in captured.err
    assert pointer.exists()
    assert outside.read_bytes() == before


def test_pickup_refuses_invalid_pointer_target(project, capsys):
    invalid = project / ".baton" / "archive" / "thin.md"
    invalid.parent.mkdir()
    invalid.write_text("# not a baton\n")
    pointer = project / ".baton" / "BATON_CURRENT"
    pointer.write_text(str(invalid))

    bg.mode_pickup({"session_id": "thin"})

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid baton" in captured.err
    assert pointer.exists()


def test_pickup_refuses_symlink_target(project, tmp_path, capsys):
    target = write_baton(project)
    link = project / ".baton" / "archive-link.md"
    link.symlink_to(target)
    pointer = project / ".baton" / "BATON_CURRENT"
    pointer.write_text(str(link))

    bg.mode_pickup({"session_id": "link"})

    assert capsys.readouterr().out == ""
    assert pointer.exists()


def test_relative_pointer_is_resolved_inside_baton_directory(project):
    archive = project / ".baton" / "archive"
    archive.mkdir()
    target = archive / "cut.md"
    target.write_text(write_baton(project).read_text())
    (project / ".baton" / "BATON_CURRENT").write_text("archive/cut.md")
    assert bg.resolve_baton_pointer(str(project)) == str(target.resolve())


def test_forged_session_id_cannot_escape_gate_directory(gate, tmp_path):
    path = bg._flag("../../escaped", "baton_due")
    assert os.path.commonpath([str(gate), os.path.realpath(path)]) == str(gate)
    assert ".." not in os.path.basename(path)


# --- compaction -------------------------------------------------------------

def test_compact_marker_records_and_says_nothing(project, gate, capsys):
    bg.mode_compact_marker({"session_id": "sJ"})
    assert capsys.readouterr().out == ""
    assert os.path.exists(gate / "sJ_baton_compacted")
    assert "compacted-without-baton" in (project / ".baton" / "batons.log").read_text()


def test_post_compact_warning_brands_the_summary_untrusted(project, gate, capsys):
    (gate / "sK_baton_compacted").write_text("1")
    bg.mode_post_compact_warn({"session_id": "sK"})
    assert "untrusted" in capsys.readouterr().out


def test_post_compact_warning_silent_when_a_baton_was_cut(project, gate, capsys):
    bg.mode_post_compact_warn({"session_id": "sL"})
    assert capsys.readouterr().out == ""


# --- fail open --------------------------------------------------------------

@pytest.mark.parametrize("mode", sorted(bg.MODES))
def test_every_mode_fails_open_on_garbage_input(mode, gate):
    r = subprocess.run([sys.executable, os.path.join(HOOKS, "baton_gate.py"), mode],
                       input="}{not json", capture_output=True, text=True,
                       env=dict(os.environ, LOOP_GATE_DIR=str(gate)))
    assert r.returncode == 0


def test_unknown_mode_fails_open(gate):
    r = run("--nonsense", {}, env={"LOOP_GATE_DIR": str(gate)})
    assert r.returncode == 0


# --- anti-collision with loop_stop_guard.py ---------------------------------
#
# loop_stop_guard.py decides a turn was a Verifier dispatch needing a run log by
# regex-matching the pass-verdict shape on task/agent/subagent/workflow tool_use
# results. Baton artifacts must never carry that shape -- in EITHER direction: they
# must not spuriously trip the gate, and must not spuriously satisfy it.

# Candidate paths per artifact: this suite runs both inside the loop framework it was
# extracted from and in the standalone repo, and a path that resolves in only one
# layout turns the check into a silent skip -- i.e. an unwritten test.
SHIPPED = [
    ("spec", ["loop-team/BATON_SPEC.md", "SPEC.md"]),
    ("project card", [".baton/PROJECT_CARD.md", "skill/templates/project_card.md"]),
]


@pytest.mark.parametrize("name,candidates", SHIPPED, ids=[s[0] for s in SHIPPED])
def test_shipped_artifacts_avoid_the_runlog_trigger_shape(name, candidates):
    import re
    root = os.path.dirname(HOOKS)
    path = next((os.path.join(root, c) for c in candidates
                 if os.path.exists(os.path.join(root, c))), None)
    if path is None:
        pytest.skip("%s not present in any known layout: %s" % (name, candidates))
    body = open(path, encoding="utf-8", errors="replace").read()
    assert not re.search(r"verdict:\s*pass", body, re.I), (
        "%s (%s) contains the shape loop_stop_guard.py matches on" % (name, path))


def test_baton_prose_in_a_read_result_does_not_trip_the_runlog_gate(tmp_path, gate):
    """A baton is read with Read, not dispatched with Agent -- the gate must ignore it."""
    guard = os.path.join(HOOKS, "loop_stop_guard.py")
    if not os.path.exists(guard):
        pytest.skip("loop_stop_guard.py not present")
    t = tmp_path / "t.jsonl"
    rows = [
        {"type": "user", "message": {"role": "user", "content": "continue the baton"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "tu1", "name": "Read",
             "input": {"file_path": str(tmp_path / "BATON.md")}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu1",
             "content": "## 7. STATE\nhooks suite green (" + PASS_VERDICT_SHAPE + ")"}]}},
    ]
    t.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    r = subprocess.run(
        [sys.executable, guard],
        input=json.dumps({"session_id": "sM", "transcript_path": str(t),
                          "cwd": str(tmp_path)}),
        capture_output=True, text=True,
        env=dict(os.environ, LOOP_GATE_DIR=str(gate)),
    )
    assert "RUNLOG_MISSING" not in (r.stderr + r.stdout)


# --- registration robustness ------------------------------------------------
#
# Regression for a bug caught in the wild on 2026-08-25: the hook code failed open,
# but the REGISTRATION did not. With baton_gate.py temporarily moved aside, python3
# exited 2 on "can't open file" and PostToolUse surfaced it as a blocking error --
# a missing file wedged a tool call. Registrations are now existence-guarded.

SETTINGS = os.path.expanduser("~/.claude/settings.json")


def _baton_commands():
    with open(SETTINGS, encoding="utf-8") as fh:
        d = json.load(fh)
    return [h.get("command", "")
            for arr in d.get("hooks", {}).values()
            for e in arr for h in e.get("hooks", [])
            if "baton_gate.py" in h.get("command", "")]


@pytest.mark.skipif(not os.path.exists(SETTINGS), reason="no user settings.json")
def test_registrations_are_existence_guarded():
    cmds = _baton_commands()
    if not cmds:
        pytest.skip("baton hooks not registered on this machine")
    for c in cmds:
        assert c.startswith("if [ -f "), (
            "unguarded registration would block a tool call when the file is "
            "absent: %s" % c)


@pytest.mark.skipif(os.name == "nt", reason="POSIX hook registration syntax")
def test_guard_exits_zero_when_the_hook_file_is_absent():
    r = subprocess.run(
        ["sh", "-c", "if [ -f /nonexistent/baton_gate.py ]; then "
                     "python3 /nonexistent/baton_gate.py --meter; fi"],
        capture_output=True, text=True)
    assert r.returncode == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX hook registration syntax")
def test_guard_still_lets_the_stop_gate_block(project, gate):
    """A plain `|| true` would swallow --gate's intentional exit 2. The `if` form
    must not."""
    (gate / "sN_target").write_text("armed")
    (gate / "sN_baton_due").write_text("%d hard:161k\n" % int(time.time()))
    script = ("if [ -f %s ]; then python3 %s --gate; fi"
              % (os.path.join(HOOKS, "baton_gate.py"),
                 os.path.join(HOOKS, "baton_gate.py")))
    r = subprocess.run(["sh", "-c", script], input=json.dumps({"session_id": "sN"}),
                       capture_output=True, text=True,
                       env=dict(os.environ, LOOP_GATE_DIR=str(gate)))
    assert r.returncode == 2
