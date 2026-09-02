#!/usr/bin/env python3
"""Control Baton automatic handoff without coupling it to any one host."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "hooks"))

import baton_runtime as runtime  # noqa: E402


def _agents(value: str):
    return ("codex", "claude") if value == "all" else (value,)


def _host_home() -> Path:
    return Path.home().expanduser().resolve()


def _auto(args):
    config = runtime.load_config(base_dir=BASE_DIR)
    root = Path(args.project).expanduser().resolve() if getattr(args, "project", None) else None
    if root:
        marker = root / ".baton" / "AUTO_HANDOFF_DISABLED"
        if args.action == "enable":
            try:
                marker.unlink()
            except FileNotFoundError:
                pass
            print("automatic handoff enabled for project: %s" % root)
        else:
            marker.parent.mkdir(parents=True, exist_ok=True)
            runtime.atomic_write_bytes(marker, b"automatic handoff disabled for this project\n")
            print("automatic handoff disabled for project: %s" % root)
        return 0
    for host in _agents(args.agent):
        config["agents"][host]["enabled"] = args.action == "enable"
    config["auto_handoff"] = any(a["enabled"] for a in config["agents"].values())
    runtime.write_config(config)
    if args.action == "enable":
        import install  # noqa: WPS433 (local checkout module)
        enabled_hosts = _agents(args.agent)
        for host in enabled_hosts:
            install.merge_host_hooks(BASE_DIR, host, home=_host_home())
        print("automatic handoff enabled for: %s" % ", ".join(enabled_hosts))
        if "codex" in enabled_hosts:
            print(
                "Codex trust step: start a new Codex session, run /hooks, review the "
                "Baton commands from ~/.codex/hooks.json, and mark those entries "
                "trusted and enabled. Then run one harmless tool call and check "
                "`python scripts/batonctl.py doctor --agent codex --json`."
            )
    else:
        print("automatic handoff disabled for: %s (hook wiring retained)" %
              ", ".join(_agents(args.agent)))
    return 0


def _status(args):
    import baton_status  # noqa: WPS433
    value = baton_status.build_status()
    config = runtime.load_config()
    value["automatic_handoff"] = config["auto_handoff"]
    value["agents"] = config["agents"]
    print(json.dumps(value, sort_keys=True))
    return 0


def _doctor(args):
    import install  # noqa: WPS433
    config = runtime.load_config()
    host = args.agent
    settings = install.host_settings_path(host, _host_home())
    states = [path for path in (runtime.runtime_home() / "state" / host).glob("*.json")
              if not path.name.startswith("handoff-")]
    errors = []
    for path in states:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and value.get("last_error"):
            errors.append(value["last_error"])
    result = {
        "agent": host,
        "configured": bool(config["auto_handoff"] and config["agents"][host]["enabled"]),
        "settings_path": str(settings),
        "settings_exists": settings.exists(),
        "hook_wiring": install.host_has_baton_hook(settings) if settings.exists() else False,
        "hook_runs_seen": bool(states),
        "automation_verified": bool(states),
        "last_errors": errors,
        "note": (
            "Use /hooks in a new Codex session to review and trust/enable each Baton "
            "entry from ~/.codex/hooks.json. hook_runs_seen proves at least one hook "
            "ran; /hooks is the authority for persisted trust."
            if host == "codex" else "Automation is unverified until a hook runs."
        ),
    }
    print(json.dumps(result, sort_keys=True))
    return 0


def _receipt(args):
    extras = {}
    for name in ("task_id", "session", "root", "baton_hash", "fingerprint"):
        value = getattr(args, name, None)
        if value:
            extras[name] = value
    runtime.record_receipt(args.handoff_id, args.provider, args.backend, **extras)
    print(json.dumps(runtime.successful_receipt(args.handoff_id), sort_keys=True))
    return 0


def _verify_state(args):
    import baton_gate  # noqa: WPS433
    root = baton_gate.project_root(args.root)
    baton = args.baton or baton_gate.current_baton(root)
    if not baton:
        print("no baton found", file=sys.stderr)
        return 2
    ok, message = runtime.verify_baton_state(str(baton), root)
    print(message)
    return 0 if ok else 1


def _snapshot(args):
    import baton_gate  # noqa: WPS433
    root = baton_gate.project_root(args.root)
    value = runtime.worktree_state(root)
    value["root"] = root
    print(json.dumps(value, sort_keys=True))
    return 0


def _uninstall(args):
    import install  # noqa: WPS433
    for host in _agents(args.agent):
        install.remove_host_hooks(BASE_DIR, host, home=_host_home())
    print("removed only Baton hook entries for: %s" % ", ".join(_agents(args.agent)))
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Baton automatic-handoff control")
    sub = parser.add_subparsers(dest="command", required=True)
    auto = sub.add_parser("auto")
    auto_sub = auto.add_subparsers(dest="action", required=True)
    for action in ("enable", "disable"):
        item = auto_sub.add_parser(action)
        group = item.add_mutually_exclusive_group(required=True)
        group.add_argument("--agent", choices=("codex", "claude", "all"))
        group.add_argument("--project")
        item.set_defaults(func=_auto)
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=_status)
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--agent", required=True, choices=("codex", "claude"))
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=_doctor)
    receipt = sub.add_parser("receipt")
    receipt.add_argument("--handoff-id", required=True)
    receipt.add_argument("--provider", required=True, choices=("codex", "claude", "custom"))
    receipt.add_argument("--backend", required=True)
    receipt.add_argument("--task-id")
    receipt.add_argument("--session")
    receipt.add_argument("--root")
    receipt.add_argument("--baton-hash")
    receipt.add_argument("--fingerprint")
    receipt.set_defaults(func=_receipt)
    verify = sub.add_parser("verify-state")
    verify.add_argument("--root")
    verify.add_argument("--baton")
    verify.set_defaults(func=_verify_state)
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--root")
    snapshot.set_defaults(func=_snapshot)
    hooks = sub.add_parser("hooks")
    hooks_sub = hooks.add_subparsers(dest="hook_action", required=True)
    uninstall = hooks_sub.add_parser("uninstall")
    uninstall.add_argument("--agent", required=True, choices=("codex", "claude", "all"))
    uninstall.set_defaults(func=_uninstall)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
