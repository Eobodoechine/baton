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


def install_copy(tmp_path):
    source = tmp_path / "repo with spaces"
    shutil.copytree(ROOT, source, symlinks=True)
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    result = subprocess.run(
        [sys.executable, str(source / "install.py")], cwd=source, env=env,
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
    assert all(command.startswith("if [ -f ") for command in cmds)
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
        [sys.executable, str(source / "install.py")], cwd=source,
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
        [sys.executable, str(source / "install.py")], cwd=source,
        env=dict(os.environ, HOME=str(home), USERPROFILE=str(home)),
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert (destination / "owner-file").read_text() == "keep"


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
