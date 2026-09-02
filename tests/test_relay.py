#!/usr/bin/env python3
"""Offline relay tests. No model process or real tmux session is started."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

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


def test_codex_headless_uses_official_exec_surface(tmp_path):
    root = project(tmp_path)
    result = run(root, "--headless", "--provider", "codex")
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("codex exec -C ")
    assert str(root) in result.stdout
    assert "BATON.md" in result.stdout


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


@pytest.mark.skipif(os.name == "nt", reason="PATH isolation fixture is POSIX-only")
def test_spawn_without_tmux_refuses_an_invisible_wait(tmp_path):
    root = project(tmp_path)
    fake_bin = isolated_posix_bin(tmp_path)
    result = run(root, "--spawn", "--provider", "claude",
                 env={"PATH": str(fake_bin)})
    assert result.returncode == 4
    assert "refusing to detach" in result.stderr
    assert "claude" in result.stdout


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


def test_custom_provider_uses_json_argv_without_a_shell(tmp_path):
    root = project(tmp_path)
    result = run(root, "--print", "--provider", "custom", env={
        "BATON_RELAY_COMMAND_JSON": '["my agent", "--repo", "{root}", "{prompt}"]',
    })
    assert result.returncode == 0, result.stderr
    assert "my agent" in result.stdout
    assert str(root) in result.stdout
    assert "Pick up the baton" in result.stdout


def test_manifest_is_validated_provider_neutral_host_input(tmp_path):
    root = project(tmp_path)
    result = run(root, "--manifest", "--provider", "codex",
                 "--parent-generation", "2", "--max-generation", "5")
    assert result.returncode == 0, result.stderr
    manifest = json.loads(result.stdout)
    assert manifest["schema_version"] == 1
    assert manifest["provider"] == "codex"
    assert manifest["root"] == str(root)
    assert manifest["generation"] == 3
    assert manifest["maximum_generation"] == 5
    assert "--parent-generation 3" in manifest["prompt"]


def test_manifest_honors_the_depth_cap(tmp_path):
    root = project(tmp_path)
    result = run(root, "--manifest", "--provider", "codex",
                 "--parent-generation", "5", "--max-generation", "5")
    assert result.returncode == 3
    assert "depth cap" in result.stderr
    assert result.stdout.startswith("codex -C ")


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
