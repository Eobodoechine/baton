#!/usr/bin/env python3
"""Cross-platform, multi-agent Baton installer (Python 3.9+)."""

import argparse
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys


def _digest(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(128 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _manifest(source):
    return {str(path.relative_to(source)): _digest(path)
            for path in source.rglob("*") if path.is_file()}


def _write_marker(destination, source, reason):
    marker = destination / ".baton-install.json"
    marker.write_text(json.dumps({
        "source": str(source),
        "reason": reason,
        "manifest": _manifest(source),
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _update_marked_copy(destination, source, data):
    old = data.get("manifest") or {}
    if not isinstance(old, dict):
        raise FileExistsError(
            "refusing to update unversioned Baton copy at %s" % destination)
    for relative, digest in old.items():
        installed = destination / relative
        if not installed.is_file() or _digest(installed) != digest:
            raise FileExistsError(
                "refusing to overwrite locally changed installed file %s" % installed)
    new = _manifest(source)
    for relative in sorted(set(old) - set(new)):
        installed = destination / relative
        if installed.is_file():
            installed.unlink()
    for relative in sorted(new):
        source_file = source / relative
        installed = destination / relative
        installed.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, installed)
    _write_marker(destination, source, data.get("reason", "symlink unavailable"))


def shell_quote(value, windows=None):
    if windows is None:
        windows = os.name == "nt"
    if windows:
        return subprocess.list2cmdline([str(value)])
    import shlex
    return shlex.quote(str(value))


def hook_config(repo, executable=None, windows=None):
    executable = executable or sys.executable
    hook = repo / "hooks" / "baton_gate.py"
    q_python = shell_quote(executable, windows=windows)
    q_hook = shell_quote(hook, windows=windows)

    def command(mode):
        if windows if windows is not None else os.name == "nt":
            return "if exist %s (%s %s %s)" % (q_hook, q_python, q_hook, mode)
        return "if [ -f %s ]; then %s %s %s; fi" % (
            q_hook, q_python, q_hook, mode)

    def entry(mode, timeout, matcher=None):
        value = {"hooks": [{"type": "command", "command": command(mode),
                             "timeout": timeout}]}
        if matcher is not None:
            value["matcher"] = matcher
        return value

    return {"hooks": {
        "PostToolUse": [entry("--meter", 10, "")],
        "UserPromptSubmit": [entry("--nag", 10, "")],
        "Stop": [entry("--gate", 10)],
        "SessionStart": [entry("--pickup", 5, "startup|resume"),
                         entry("--post-compact-warn", 5, "compact")],
        "PreCompact": [entry("--compact-marker", 5, "auto")],
    }}


def _skills_dir(agent, home):
    if agent == "codex":
        return Path(os.environ.get("CODEX_SKILLS_DIR", home / ".codex" / "skills"))
    if agent == "claude":
        return Path(os.environ.get("CLAUDE_SKILLS_DIR", home / ".claude" / "skills"))
    raise ValueError("agent must be 'codex' or 'claude'")


def detect_agents(home=None):
    """Return every locally detectable supported agent, in neutral order."""
    home = Path(home or Path.home()).resolve()
    detected = []
    for agent in ("codex", "claude"):
        if (home / (".%s" % agent)).exists() or shutil.which(agent):
            detected.append(agent)
    return detected


def install(repo=None, home=None, skills_dir=None, output=None, agent=None):
    output = output or sys.stdout
    repo = Path(repo or Path(__file__).resolve().parent).resolve()
    home = Path(home or Path.home()).resolve()
    source = repo / "skill"
    if skills_dir is None:
        if agent not in ("codex", "claude"):
            raise ValueError("choose agent='codex' or agent='claude'")
        skills = _skills_dir(agent, home).expanduser()
    else:
        skills = Path(skills_dir).expanduser()
    destination = skills / "baton"
    skills.mkdir(parents=True, exist_ok=True)

    method = "symlink"
    if destination.is_symlink() and destination.resolve() == source:
        print("already installed: %s -> %s" % (destination, source), file=output)
    elif destination.exists() or destination.is_symlink():
        marker = destination / ".baton-install.json" if destination.is_dir() else None
        if marker and marker.is_file():
            try:
                data = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            if data.get("source") == str(source):
                method = "copy"
                _update_marked_copy(destination, source, data)
                print("updated marked copy: %s" % destination, file=output)
            else:
                raise FileExistsError(
                    "refusing to overwrite existing %s; move it aside first" %
                    destination)
        else:
            raise FileExistsError(
                "refusing to overwrite existing %s; move it aside first" % destination)
    else:
        try:
            destination.symlink_to(source, target_is_directory=True)
            print("linked %s -> %s" % (destination, source), file=output)
        except OSError as exc:
            # Windows commonly denies unprivileged directory symlinks. A marked copy
            # gives users a working installation without deleting or overwriting.
            shutil.copytree(source, destination)
            _write_marker(destination, source, str(exc))
            method = "copy"
            print("symlink unavailable; copied skill to %s" % destination,
                  file=output)

    config = home / ".baton-config"
    config.write_text("base_dir=%s\n" % repo, encoding="utf-8")
    try:
        config.chmod(0o600)
    except OSError:
        pass
    print("wrote %s (base_dir=%s)" % (config, repo), file=output)
    return destination, method


def _requested_agents(values, home):
    if not values:
        detected = detect_agents(home)
        if detected:
            return detected
        raise ValueError(
            "could not detect Codex or Claude Code; rerun with --agent codex or "
            "--agent claude")
    expanded = []
    for value in values:
        names = ("codex", "claude") if value == "all" else (value,)
        for name in names:
            if name not in expanded:
                expanded.append(name)
    return expanded


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Install the Baton skill")
    parser.add_argument(
        "--agent", action="append", choices=("codex", "claude", "all"),
        help="install target; repeat or use 'all' (default: detect installed agents)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        repo = Path(__file__).resolve().parent
        home = Path.home().resolve()
        agents = _requested_agents(args.agent, home)
        for agent in agents:
            install(repo=repo, home=home, agent=agent)
    except (FileExistsError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("\nInstalled for: %s" % ", ".join(agents))
    if "claude" in agents:
        print("\nOptional Claude Code hook configuration. Merge this object into "
              "your Claude Code settings:")
        print("--- BEGIN BATON HOOK JSON ---")
        print(json.dumps(hook_config(repo), indent=2, sort_keys=True))
        print("--- END BATON HOOK JSON ---")
    print("\nRun the receiver-neutral relay with Python on any platform. "
          "tmux is optional; see README.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
