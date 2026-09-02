#!/usr/bin/env python3
"""Offline relay tests. No model process or real tmux session is started."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
RELAY = ROOT / "scripts" / "baton_next.py"
sys.path.insert(0, str(ROOT / "scripts"))
import baton_next as relay  # noqa: E402


def valid_body(root="/tmp/example"):
    return """# BATON — relay test
Detail tier: brief
Repo: {root}
Card: .baton/PROJECT_CARD.md @ deadbeef
Trust rule: verify this file against the repository.

## 1. DO THIS NOW
Run: python -m pytest
Expected: green

## 2. WHERE YOU ARE
Run: git status

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
""".format(root=root)


def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".baton").mkdir()
    (root / ".baton" / "BATON.md").write_text(valid_body(str(root)))
    return root


def run(root, *args, env=None):
    merged = dict(os.environ, HOME=str(root / "home"))
    (root / "home").mkdir(exist_ok=True)
    # A real successor inherits the relay controls that launched it. Tests must
    # opt into those controls explicitly; otherwise a parent session can change
    # the behavior being exercised and make the suite host-dependent.
    for key in (
        "BATON_RELAY_GEN",
        "BATON_RELAY_MAX_GEN",
        "BATON_RELAY_MODEL",
        "BATON_RELAY_PERMISSION_MODE",
        "BATON_RELAY_PROVIDER",
        "BATON_RELAY_SANDBOX",
        "BATON_RELAY_APPROVAL_POLICY",
        "BATON_RELAY_COMMAND_JSON",
        "BATON_RELAY_HEADLESS_COMMAND_JSON",
    ):
        merged.pop(key, None)
    merged.update(env or {})
    return subprocess.run(
        [sys.executable, str(RELAY), *args], cwd=root, env=merged,
        capture_output=True, text=True,
    )


def isolated_posix_bin(tmp_path):
    """Return a PATH with Git but without host-installed receivers or tmux."""
    fake_bin = tmp_path / "isolated-bin"
    fake_bin.mkdir()
    git = shutil.which("git")
    assert git is not None
    (fake_bin / "git").symlink_to(git)
    return fake_bin


def test_claude_headless_prints_a_shell_escaped_command(tmp_path):
    root = project(tmp_path)
    result = run(root, "--headless", "--provider", "claude")
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("claude -p ")
    assert "BATON.md" in result.stdout


def test_codex_headless_uses_official_exec_surface(tmp_path, monkeypatch):
    root = project(tmp_path)
    monkeypatch.delenv("BATON_RELAY_SANDBOX", raising=False)
    monkeypatch.delenv("BATON_RELAY_APPROVAL_POLICY", raising=False)
    baton = root / ".baton" / "BATON.md"
    prompt = relay.relay_prompt(str(baton), 1, 5)
    adapter = relay.build_adapter("codex", str(root), str(baton), prompt, "")
    result = run(root, "--headless", "--provider", "codex")
    assert result.returncode == 0, result.stderr
    argv = adapter["headless"]
    assert result.stdout.strip() == relay.format_command(argv)
    assert argv[0] == "codex"
    assert "exec" in argv
    assert argv[argv.index("-C") + 1] == str(root)
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv.index("--sandbox") < argv.index("exec")
    assert "BATON.md" in argv[-1]


def test_codex_0146_global_approval_option_precedes_exec(tmp_path, monkeypatch):
    root = project(tmp_path)
    monkeypatch.setenv("BATON_RELAY_APPROVAL_POLICY", "never")
    baton = root / ".baton" / "BATON.md"
    prompt = relay.relay_prompt(str(baton), 1, 5)
    adapter = relay.build_adapter("codex", str(root), str(baton), prompt, "")
    result = run(root, "--headless", "--provider", "codex", env={
        "BATON_RELAY_APPROVAL_POLICY": "never",
    })
    assert result.returncode == 0, result.stderr
    argv = adapter["headless"]
    assert result.stdout.strip() == relay.format_command(argv)
    approval = argv.index("--ask-for-approval")
    subcommand = argv.index("exec")
    assert argv[approval + 1] == "never"
    assert approval < subcommand


def test_codex_never_approval_still_warns_about_login(tmp_path, monkeypatch):
    root = project(tmp_path)
    monkeypatch.setenv("BATON_RELAY_APPROVAL_POLICY", "never")
    adapter = relay.build_adapter(
        "codex", str(root), str(root / ".baton" / "BATON.md"), "prompt", "")
    assert "login" in adapter["wait_warning"].lower()


def test_command_formatting_supports_windows_and_posix():
    args = ["receiver", "a path with spaces", 'a "quote"']
    assert relay.format_command(args, windows=False).startswith("receiver ")
    assert relay.format_command(args, windows=True).startswith("receiver ")
    assert "a path with spaces" in relay.format_command(args, windows=True)


def test_relay_refuses_pointer_outside_repository(tmp_path):
    root = project(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text(valid_body(str(root)))
    (root / ".baton" / "BATON_CURRENT").write_text(str(outside))
    result = run(root, "--headless", "--provider", "codex")
    assert result.returncode == 5
    assert "outside" in result.stderr


def test_relay_uses_linter_not_substring_presence(tmp_path):
    root = project(tmp_path)
    baton = root / ".baton" / "BATON.md"
    baton.write_text(valid_body(str(root)).replace(
        "## 4. DO NOT RETRY\nnone",
        "## 9. GOTCHAS\n```markdown\n## 4. DO NOT RETRY\n```",
    ))
    result = run(root, "--headless", "--provider", "codex")
    assert result.returncode == 5
    assert "missing mandatory section: ## 4" in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="fake tmux fixture is POSIX-only")
def test_spawn_uses_fake_tmux_and_never_starts_a_real_model(tmp_path):
    root = project(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "tmux-calls"
    tmux = fake_bin / "tmux"
    tmux.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$FAKE_TMUX_CALLS\"\n"
        "[ \"${1:-}\" = has-session ] && exit 1\n"
        "exit 0\n"
    )
    tmux.chmod(0o755)
    codex = fake_bin / "codex"
    codex.write_text("#!/bin/sh\necho should-not-run-directly\n")
    codex.chmod(0o755)
    result = run(root, "--spawn", "--provider", "codex", env={
        "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
        "FAKE_TMUX_CALLS": str(calls),
    })
    assert result.returncode == 0, result.stderr
    assert "successor started" in result.stdout
    assert "provider   codex" in result.stdout
    assert "new-session" in calls.read_text()
    logged = (root / ".baton" / "batons.log").read_text()
    assert "\trelay\t" in logged
    assert "provider=codex" in logged
    receipts = list((root / "home" / ".baton" / "receipts").glob("*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt["status"] == "launched"
    # A retry must recover the receipt before querying/creating another tmux session.
    before_retry_calls = calls.read_text()
    retry = run(root, "--spawn", "--provider", "codex", env={
        "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
        "FAKE_TMUX_CALLS": str(calls),
    })
    assert retry.returncode == 0
    assert "recovered existing launch receipt" in retry.stdout
    assert calls.read_text() == before_retry_calls


@pytest.mark.skipif(os.name == "nt", reason="PATH isolation fixture is POSIX-only")
def test_spawn_without_tmux_refuses_an_invisible_wait(tmp_path):
    root = project(tmp_path)
    fake_bin = isolated_posix_bin(tmp_path)
    result = run(root, "--spawn", "--provider", "claude",
                 env={"PATH": str(fake_bin)})
    assert result.returncode == 4
    assert "refusing to detach" in result.stderr
    assert "claude" in result.stdout
    receipts_dir = root / "home" / ".baton" / "receipts"
    assert not receipts_dir.exists() or not list(receipts_dir.glob("*.json"))


@pytest.mark.skipif(os.name == "nt", reason="PATH isolation fixture is POSIX-only")
def test_relay_tests_ignore_parent_session_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("BATON_RELAY_GEN", "4")
    monkeypatch.setenv("BATON_RELAY_MAX_GEN", "1")
    monkeypatch.setenv("BATON_RELAY_MODEL", "parent-model")
    monkeypatch.setenv("BATON_RELAY_PERMISSION_MODE", "auto")
    monkeypatch.setenv("BATON_RELAY_PROVIDER", "codex")
    monkeypatch.setenv("BATON_RELAY_SANDBOX", "danger-full-access")
    monkeypatch.setenv("BATON_RELAY_APPROVAL_POLICY", "never")
    monkeypatch.setenv("BATON_RELAY_COMMAND_JSON", '["parent-agent"]')
    monkeypatch.setenv("BATON_RELAY_HEADLESS_COMMAND_JSON", '["parent-headless"]')
    root = project(tmp_path)
    fake_bin = isolated_posix_bin(tmp_path)
    result = run(root, "--spawn", "--provider", "claude",
                 env={"PATH": str(fake_bin)})
    assert result.returncode == 4
    assert "refusing to detach" in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="fake executable fixture is POSIX-only")
def test_spawn_without_tmux_can_use_explicit_headless_backend(tmp_path):
    root = project(tmp_path)
    fake_bin = isolated_posix_bin(tmp_path)
    claude = fake_bin / "claude"
    claude.write_text("#!/bin/sh\necho fake-claude-finished\n")
    claude.chmod(0o755)
    result = run(root, "--spawn", "--provider", "claude", env={
        "PATH": str(fake_bin),
        "BATON_RELAY_PERMISSION_MODE": "acceptEdits",
    })
    assert result.returncode == 0, result.stderr
    assert "detached-headless" in result.stdout
    assert "backend=detached-headless" in (
        root / ".baton" / "batons.log").read_text()


@pytest.mark.skipif(os.name == "nt", reason="fake executable fixture is POSIX-only")
def test_codex_can_use_safe_noninteractive_backend_without_tmux(tmp_path):
    root = project(tmp_path)
    fake_bin = isolated_posix_bin(tmp_path)
    codex = fake_bin / "codex"
    codex.write_text("#!/bin/sh\necho fake-codex-finished\n")
    codex.chmod(0o755)
    result = run(root, "--spawn", "--provider", "codex", env={
        "PATH": str(fake_bin),
        "BATON_RELAY_SANDBOX": "workspace-write",
        "BATON_RELAY_APPROVAL_POLICY": "never",
    })
    assert result.returncode == 0, result.stderr
    assert "provider   codex" in result.stdout
    assert "detached-headless" in result.stdout
    assert "sandbox=workspace-write" in result.stdout
    assert "provider=codex" in (
        root / ".baton" / "batons.log").read_text()


@pytest.mark.skipif(os.name == "nt", reason="fake executable fixture is POSIX-only")
def test_auto_provider_selects_the_only_installed_receiver(tmp_path):
    root = project(tmp_path)
    fake_bin = isolated_posix_bin(tmp_path)
    codex = fake_bin / "codex"
    codex.write_text("#!/bin/sh\nexit 0\n")
    codex.chmod(0o755)
    result = run(root, "--print", env={
        "PATH": str(fake_bin),
    })
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("codex -C ")


@pytest.mark.skipif(os.name == "nt", reason="fake executable fixture is POSIX-only")
def test_auto_provider_refuses_to_guess_when_both_are_installed(tmp_path):
    root = project(tmp_path)
    fake_bin = isolated_posix_bin(tmp_path)
    for name in ("codex", "claude"):
        executable = fake_bin / name
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
    result = run(root, "--print", env={
        "PATH": str(fake_bin),
    })
    assert result.returncode == 2
    assert "found both" in result.stderr
    assert "--provider codex" in result.stderr


def test_custom_provider_preserves_json_argv_as_literals_when_printed(
        tmp_path, monkeypatch):
    root = project(tmp_path)
    payload = "literal; value with $(syntax)"
    raw = json.dumps(["my agent", "--repo", "{root}", payload, "{prompt}"])
    monkeypatch.setenv("BATON_RELAY_COMMAND_JSON", raw)
    baton = root / ".baton" / "BATON.md"
    prompt = relay.relay_prompt(str(baton), 1, 5)
    adapter = relay.build_adapter("custom", str(root), str(baton), prompt, "")
    result = run(root, "--print", "--provider", "custom", env={
        "BATON_RELAY_COMMAND_JSON": raw,
    })
    assert result.returncode == 0, result.stderr
    argv = adapter["interactive"]
    assert result.stdout.strip() == relay.format_command(argv)
    assert argv[:4] == ["my agent", "--repo", str(root), payload]
    assert argv[4].startswith("Pick up the baton")


@pytest.mark.skipif(os.name == "nt", reason="fake tmux fixture is POSIX-only")
def test_tmux_receives_adversarial_custom_command_as_direct_argv(tmp_path):
    root = project(tmp_path)
    fake_bin = isolated_posix_bin(tmp_path)
    calls = tmp_path / "tmux-calls.jsonl"
    sentinel = tmp_path / "must-not-exist"
    tmux = fake_bin / "tmux"
    tmux.write_text(
        "#!%s\n" % sys.executable +
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "with Path(os.environ['FAKE_TMUX_CALLS']).open('a') as fh:\n"
        "    fh.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "raise SystemExit(1 if sys.argv[1:2] == ['has-session'] else 0)\n"
    )
    tmux.chmod(0o755)
    receiver = fake_bin / "custom receiver"
    receiver.write_text("#!/bin/sh\nexit 0\n")
    receiver.chmod(0o755)
    payload = "literal; touch %s; $(touch %s)" % (sentinel, sentinel)
    result = run(root, "--spawn", "--provider", "custom", env={
        "PATH": str(fake_bin),
        "FAKE_TMUX_CALLS": str(calls),
        "BATON_RELAY_COMMAND_JSON": json.dumps([
            str(receiver), "--literal", payload, "{prompt}",
        ]),
    })
    assert result.returncode == 0, result.stderr
    recorded = [json.loads(line) for line in calls.read_text().splitlines()]
    launched = next(call for call in recorded if call[:1] == ["new-session"])
    receiver_index = launched.index(str(receiver))
    assert launched[receiver_index:receiver_index + 3] == [
        str(receiver), "--literal", payload,
    ]
    assert launched[receiver_index + 3].startswith("Pick up the baton")
    assert not sentinel.exists()


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("tmux") is None or
    os.environ.get("BATON_LIVE_TMUX") != "1",
    reason="set BATON_LIVE_TMUX=1 to exercise the installed tmux",
)
def test_live_tmux_executes_custom_argv_without_a_shell(tmp_path):
    tmux = shutil.which("tmux")
    capture_script = tmp_path / "capture-live-tmux.py"
    captured = tmp_path / "captured-live-tmux.json"
    sentinel = tmp_path / "must-not-exist"
    capture_script.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))\n"
    )
    payload = "literal; touch %s; $(touch %s)" % (sentinel, sentinel)
    session = "baton-live-argv-%s" % os.getpid()
    log = tmp_path / "tmux.log"
    try:
        relay._tmux_spawn(tmux, str(tmp_path), session, [
            sys.executable, str(capture_script), str(captured), payload,
        ], log)
        for _ in range(100):
            if captured.exists():
                break
            time.sleep(0.02)
        assert captured.exists()
        assert json.loads(captured.read_text()) == [payload]
        assert not sentinel.exists()
    finally:
        subprocess.run(
            [tmux, "kill-session", "-t", "=" + session],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


@pytest.mark.skipif(os.name == "nt", reason="detached test uses a POSIX PATH fixture")
def test_custom_detached_backend_passes_argv_directly(tmp_path):
    root = project(tmp_path)
    fake_bin = isolated_posix_bin(tmp_path)
    capture_script = tmp_path / "capture-detached.py"
    captured = tmp_path / "captured-detached.json"
    sentinel = tmp_path / "must-not-exist"
    capture_script.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))\n"
    )
    payload = "literal; touch %s" % sentinel
    headless = json.dumps([
        sys.executable, str(capture_script), str(captured), "{baton}", payload,
        "{prompt}",
    ])
    result = run(root, "--spawn", "--provider", "custom", env={
        "PATH": str(fake_bin),
        "BATON_RELAY_COMMAND_JSON": json.dumps([sys.executable, "{prompt}"]),
        "BATON_RELAY_HEADLESS_COMMAND_JSON": headless,
    })
    assert result.returncode == 0, result.stderr
    for _ in range(100):
        if captured.exists():
            break
        time.sleep(0.02)
    assert captured.exists()
    argv = json.loads(captured.read_text())
    assert argv[0] == str(root / ".baton" / "BATON.md")
    assert argv[1] == payload
    assert argv[2].startswith("Pick up the baton")
    assert not sentinel.exists()


def test_manifest_is_validated_provider_neutral_host_input(tmp_path):
    root = project(tmp_path)
    result = run(root, "--manifest", "--provider", "codex",
                 "--parent-generation", "2", "--max-generation", "5")
    assert result.returncode == 0, result.stderr
    manifest = json.loads(result.stdout)
    assert manifest["schema_version"] == 2
    assert manifest["provider"] == "codex"
    assert manifest["root"] == str(root)
    assert manifest["generation"] == 3
    assert manifest["maximum_generation"] == 5
    assert "--parent-generation 3" in manifest["prompt"]
    assert len(manifest["handoff_id"]) == 64
    assert manifest["handoff_id"] in manifest["successor_title"]
    assert manifest["receipt_recording_argv"][2:4] == ["receipt", "--handoff-id"]


def test_manifest_honors_the_depth_cap(tmp_path):
    root = project(tmp_path)
    result = run(root, "--manifest", "--provider", "codex",
                 "--parent-generation", "5", "--max-generation", "5")
    assert result.returncode == 3
    assert "depth cap" in result.stderr
    assert result.stdout.startswith("codex -C ")


@pytest.mark.skipif(os.name == "nt", reason="fake tmux fixture is POSIX-only")
def test_unrelated_deterministic_session_collision_keeps_exit_six(tmp_path):
    root = project(tmp_path)
    manifest_result = run(root, "--manifest", "--provider", "codex")
    assert manifest_result.returncode == 0
    manifest = json.loads(manifest_result.stdout)
    session = "baton-project-codex-g1-%s" % manifest["handoff_id"][:16]
    relay_dir = root / ".baton" / "relay"
    relay_dir.mkdir()
    (relay_dir / (session + ".handoff")).write_text("not-this-handoff\n")
    fake_bin = tmp_path / "collision-bin"
    fake_bin.mkdir()
    tmux = fake_bin / "tmux"
    tmux.write_text("#!/bin/sh\nexit 0\n")
    tmux.chmod(0o755)
    codex = fake_bin / "codex"
    codex.write_text("#!/bin/sh\nexit 0\n")
    codex.chmod(0o755)
    result = run(root, "--spawn", "--provider", "codex", env={
        "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
    })
    assert result.returncode == 6
    assert "another handoff" in result.stderr


def test_invalid_codex_policy_fails_before_launch(tmp_path):
    root = project(tmp_path)
    result = run(root, "--manifest", "--provider", "codex", env={
        "BATON_RELAY_SANDBOX": "everything",
    })
    assert result.returncode == 2
    assert "BATON_RELAY_SANDBOX" in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="PATH isolation fixture is POSIX-only")
def test_auto_provider_reports_when_no_receiver_is_installed(tmp_path):
    root = project(tmp_path)
    fake_bin = isolated_posix_bin(tmp_path)
    result = run(root, "--print", env={"PATH": str(fake_bin)})
    assert result.returncode == 7
    assert "found neither" in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="PATH isolation fixture is POSIX-only")
def test_custom_provider_without_headless_argv_refuses_detach(tmp_path):
    root = project(tmp_path)
    fake_bin = isolated_posix_bin(tmp_path)
    result = run(root, "--spawn", "--provider", "custom", env={
        "PATH": str(fake_bin),
        "BATON_RELAY_COMMAND_JSON": '["my-agent", "{prompt}"]',
    })
    assert result.returncode == 4
    assert "no explicitly safe headless" in result.stderr
    assert "my-agent" in result.stdout
