#!/usr/bin/env python3
"""Installer output and safety regression tests."""

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import install as installer  # noqa: E402


def install_copy(tmp_path, agent="claude"):
    source = tmp_path / "repo with spaces"
    shutil.copytree(ROOT, source, symlinks=True)
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    result = subprocess.run(
        [sys.executable, str(source / "install.py"), "--agent", agent],
        cwd=source, env=env,
        capture_output=True, text=True,
    )
    return source, home, result


def hook_json(stdout):
    payload = stdout.split("--- BEGIN BATON HOOK JSON ---", 1)[1]
    payload = payload.split("--- END BATON HOOK JSON ---", 1)[0]
    return json.loads(payload)


def commands(config):
    return [
        hook["command"]
        for entries in config["hooks"].values()
        for entry in entries
        for hook in entry["hooks"]
    ]


def test_installer_prints_parseable_guarded_json_with_quoted_paths(tmp_path):
    source, home, result = install_copy(tmp_path)
    assert result.returncode == 0, result.stderr
    config = hook_json(result.stdout)
    cmds = commands(config)
    assert len(cmds) == 6
    expected_guard = "if exist " if os.name == "nt" else "if [ -f "
    assert all(command.startswith(expected_guard) for command in cmds)
    assert all(str(source / "hooks" / "baton_gate.py") in command for command in cmds)
    if os.name != "nt":
        for command in cmds:
            checked = subprocess.run(["sh", "-n", "-c", command])
            assert checked.returncode == 0

    link = home / ".claude" / "skills" / "baton"
    assert link.exists()
    if link.is_symlink():
        assert link.resolve() == source / "skill"
    else:
        assert (link / ".baton-install.json").is_file()
    if os.name != "nt":
        mode = stat.S_IMODE((home / ".baton-config").stat().st_mode)
        assert mode == 0o600


def test_installer_is_idempotent_for_its_own_link(tmp_path):
    source, home, first = install_copy(tmp_path)
    assert first.returncode == 0
    second = subprocess.run(
        [sys.executable, str(source / "install.py"), "--agent", "claude"],
        cwd=source,
        env=dict(os.environ, HOME=str(home), USERPROFILE=str(home)),
        capture_output=True, text=True,
    )
    assert second.returncode == 0
    assert ("already installed" in second.stdout or
            "updated marked copy" in second.stdout)


def test_installer_refuses_to_overwrite_an_existing_skill(tmp_path):
    source = tmp_path / "repo"
    shutil.copytree(ROOT, source, symlinks=True)
    home = tmp_path / "home"
    destination = home / ".claude" / "skills" / "baton"
    destination.mkdir(parents=True)
    (destination / "owner-file").write_text("keep")
    result = subprocess.run(
        [sys.executable, str(source / "install.py"), "--agent", "claude"],
        cwd=source,
        env=dict(os.environ, HOME=str(home), USERPROFILE=str(home)),
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert (destination / "owner-file").read_text() == "keep"
    assert "outside" in result.stderr
    assert "duplicate skills" in result.stderr


def test_windows_hook_commands_are_guarded_and_quoted():
    config = installer.hook_config(
        Path(r"C:\Users\Example User\baton"),
        executable=Path(r"C:\Program Files\Python\python.exe"),
        windows=True,
    )
    cmds = commands(config)
    assert all(command.startswith("if exist ") for command in cmds)
    assert all('"C:\\Program Files\\Python\\python.exe"' in command
               for command in cmds)


def test_installer_falls_back_to_a_marked_copy_when_symlink_is_unavailable(
        tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()

    def denied(*args, **kwargs):
        raise OSError("symlink privilege unavailable")

    monkeypatch.setattr(Path, "symlink_to", denied)
    destination, method = installer.install(
        repo=ROOT, home=home, skills_dir=home / "skills")
    assert method == "copy"
    marker = destination / ".baton-install.json"
    assert marker.is_file()
    assert json.loads(marker.read_text())["source"] == str(ROOT / "skill")


def test_marked_copy_updates_only_when_installed_files_are_unchanged(
        tmp_path, monkeypatch):
    source = tmp_path / "source"
    shutil.copytree(ROOT, source, symlinks=True)
    home = tmp_path / "home"
    home.mkdir()

    def denied(*args, **kwargs):
        raise OSError("symlink privilege unavailable")

    monkeypatch.setattr(Path, "symlink_to", denied)
    destination, method = installer.install(
        repo=source, home=home, skills_dir=home / "skills")
    assert method == "copy"
    updated = source / "skill" / "README.md"
    updated.write_text(updated.read_text() + "\nupdate marker\n")
    installer.install(repo=source, home=home, skills_dir=home / "skills")
    assert "update marker" in (destination / "README.md").read_text()

    (destination / "README.md").write_text("owner change\n")
    updated.write_text(updated.read_text() + "\nsecond update\n")
    with pytest.raises(FileExistsError, match="locally changed"):
        installer.install(repo=source, home=home, skills_dir=home / "skills")


def test_installer_supports_codex_without_a_claude_directory(tmp_path):
    source, home, result = install_copy(tmp_path, agent="codex")
    assert result.returncode == 0, result.stderr
    assert "Installed for: codex" in result.stdout
    assert "BEGIN BATON HOOK JSON" not in result.stdout
    link = home / ".codex" / "skills" / "baton"
    assert link.exists()
    if link.is_symlink():
        assert link.resolve() == source / "skill"
    assert not (home / ".claude").exists()


def test_distributed_skill_does_not_require_claude_project_instructions():
    instructions = (ROOT / "skill" / "SKILL.md").read_text(encoding="utf-8")
    template = (ROOT / "skill" / "templates" / "project_card.md").read_text(
        encoding="utf-8")
    normalized = " ".join(instructions.split())
    normalized_template = " ".join(template.split())
    assert "No vendor-specific instruction file is required" in normalized
    assert "`AGENTS.md`" in instructions
    assert "using the project's `CLAUDE.md`" not in instructions
    assert "applicable agent instructions" in normalized_template


def test_installer_can_target_both_supported_agents(tmp_path):
    source = tmp_path / "repo"
    shutil.copytree(ROOT, source, symlinks=True)
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        [sys.executable, str(source / "install.py"), "--agent", "all"],
        cwd=source,
        env=dict(os.environ, HOME=str(home), USERPROFILE=str(home)),
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Installed for: codex, claude" in result.stdout
    assert (home / ".codex" / "skills" / "baton").exists()
    assert (home / ".claude" / "skills" / "baton").exists()


def test_auto_detection_returns_all_present_supported_agents(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".claude").mkdir()
    monkeypatch.setattr(installer.shutil, "which", lambda _name: None)
    assert installer.detect_agents(home) == ["codex", "claude"]


def test_auto_detection_does_not_default_to_claude(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(installer.shutil, "which", lambda _name: None)
    with pytest.raises(ValueError, match="could not detect"):
        installer._requested_agents(None, home)


def test_install_writes_versioned_runtime_config_but_keeps_automation_off(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    installer.install(repo=ROOT, home=home, skills_dir=home / "skills")
    config = json.loads((home / ".baton" / "config.json").read_text())
    assert config["schema_version"] == 1
    assert config["auto_handoff"] is False
    assert config["agents"]["codex"]["enabled"] is False
    assert (home / ".baton-config").read_text().startswith("base_dir=")


def test_install_honors_explicit_baton_home_override(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    override = tmp_path / "runtime-override"
    monkeypatch.setenv("BATON_HOME", str(override))
    installer.install(repo=ROOT, home=home, skills_dir=home / "skills")
    assert (override / "config.json").is_file()
    assert not (home / ".baton" / "config.json").exists()
    assert (home / ".baton-config").is_file()


def test_hook_merge_preserves_unrelated_entries_and_is_idempotent(tmp_path):
    home = tmp_path / "home"
    settings = home / ".codex" / "hooks.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"hooks": {
        "PostToolUse": [{"hooks": [{"type": "command", "command": "owner-hook"}]}],
    }}))
    installer.merge_host_hooks(ROOT, "codex", home=home)
    installer.merge_host_hooks(ROOT, "codex", home=home)
    value = json.loads(settings.read_text())
    commands = [command for entries in value["hooks"].values() for entry in entries
                for command in installer._hook_commands(entry)]
    assert commands.count("owner-hook") == 1
    assert len([command for command in commands if "baton_gate.py" in command and
                "--meter" in command]) == 1
    assert (settings.with_name("hooks.json.baton-backup")).is_file()


def test_hook_merge_refuses_malformed_json_without_overwrite(tmp_path):
    home = tmp_path / "home"
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("not json")
    with pytest.raises(ValueError, match="malformed JSON"):
        installer.merge_host_hooks(ROOT, "claude", home=home)
    assert settings.read_text() == "not json"


def test_hook_uninstall_removes_only_baton_entries(tmp_path):
    home = tmp_path / "home"
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": "owner-stop"}]}],
    }}))
    installer.merge_host_hooks(ROOT, "claude", home=home)
    installer.remove_host_hooks(ROOT, "claude", home=home)
    value = json.loads(settings.read_text())
    commands = [command for entries in value["hooks"].values() for entry in entries
                for command in installer._hook_commands(entry)]
    assert commands == ["owner-stop"]


def test_batonctl_global_enable_disable_and_project_override(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    runtime = tmp_path / "runtime"
    project = tmp_path / "project"
    (project / ".baton").mkdir(parents=True)
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), BATON_HOME=str(runtime))
    ctl = ROOT / "scripts" / "batonctl.py"
    enabled = subprocess.run([sys.executable, str(ctl), "auto", "enable", "--agent", "codex"],
                             env=env, cwd=ROOT, capture_output=True, text=True)
    assert enabled.returncode == 0, enabled.stderr
    assert "run /hooks" in enabled.stdout
    assert "trusted and enabled" in enabled.stdout
    config = json.loads((runtime / "config.json").read_text())
    assert config["auto_handoff"] and config["agents"]["codex"]["enabled"]
    assert (home / ".codex" / "hooks.json").is_file()
    disabled_project = subprocess.run(
        [sys.executable, str(ctl), "auto", "disable", "--project", str(project)],
        env=env, cwd=ROOT, capture_output=True, text=True)
    assert disabled_project.returncode == 0
    assert (project / ".baton" / "AUTO_HANDOFF_DISABLED").is_file()
    disabled = subprocess.run([sys.executable, str(ctl), "auto", "disable", "--agent", "codex"],
                               env=env, cwd=ROOT, capture_output=True, text=True)
    assert disabled.returncode == 0, disabled.stderr
    config = json.loads((runtime / "config.json").read_text())
    assert config["auto_handoff"] is False
    assert (home / ".codex" / "hooks.json").is_file()
