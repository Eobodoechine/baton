#!/usr/bin/env python3
"""Cross-platform, receiver-neutral Baton relay.

The validation and command-building path is standard-library Python. Built-in
adapters support Codex and Claude Code. A JSON argv adapter supports other agents
without routing receiver arguments through a shell. tmux is optional: it provides an
attachable interactive receiver, while provider-specific non-interactive commands
provide the safe detached fallback.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

BASE_DIR = Path(__file__).resolve().parents[1]
HOOKS_DIR = BASE_DIR / "hooks"
sys.path.insert(0, str(HOOKS_DIR))
import baton_gate  # noqa: E402


PROVIDERS = ("auto", "codex", "claude", "custom")
CODEX_SANDBOXES = ("read-only", "workspace-write", "danger-full-access")
CODEX_APPROVALS = ("untrusted", "on-request", "never")


def format_command(args, windows=None):
    if windows is None:
        windows = os.name == "nt"
    return subprocess.list2cmdline(args) if windows else shlex.join(args)


def load_baton():
    root = baton_gate.project_root()
    try:
        baton = baton_gate.current_baton(root, require_valid=False)
    except baton_gate.BatonPointerError as exc:
        raise baton_gate.BatonPointerError("unsafe BATON_CURRENT: %s" % exc)
    if not baton:
        raise FileNotFoundError("no baton found in %s — cut one first (/baton cut)"
                                % baton_gate.baton_dir(root))
    return root, baton


def lint_baton(path):
    candidates = (
        BASE_DIR / "evals" / "lint_baton.py",
        BASE_DIR / "loop-team" / "evals" / "baton" / "lint_baton.py",
    )
    linter = next((candidate for candidate in candidates if candidate.is_file()), None)
    if linter is None:
        return False, "linter missing; checked %s" % ", ".join(
            str(candidate) for candidate in candidates)
    result = subprocess.run(
        [sys.executable, str(linter), path], capture_output=True, text=True,
    )
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output


def baton_tier(path):
    try:
        head = Path(path).read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        return "unknown"
    match = re.search(r"^(?:Detail|Receiver) tier:\s*(\w+)", head, re.M)
    return match.group(1) if match else "unknown"


def relay_prompt(path, generation, maximum):
    return """Pick up the baton. Read {path} and execute it.

Run the section 2 invariant check BEFORE touching anything. If it does not match, STOP
and report the mismatch — do not improvise around it. Then execute section 3 in order,
running each step's verify command. Do not do anything the baton does not ask for.

(Baton relay generation {generation} of {maximum}. If this receiver later cuts another
baton, pass --parent-generation {generation} to baton_next.py, or export
BATON_RELAY_GEN={generation}, so the chain-depth cap remains intact. At {maximum} the
chain stops and waits for a human.)""".format(
        path=path, generation=generation, maximum=maximum,
    )


def _parse_nonnegative(value, name):
    if value is None or not str(value).isdigit():
        raise ValueError("%s must be a non-negative integer" % name)
    return int(value)


def relay_position(parent_generation=None, maximum=None):
    raw_parent = (os.environ.get("BATON_RELAY_GEN", "0")
                  if parent_generation is None else parent_generation)
    raw_maximum = (os.environ.get("BATON_RELAY_MAX_GEN", "5")
                   if maximum is None else maximum)
    parent = _parse_nonnegative(raw_parent, "BATON_RELAY_GEN/--parent-generation")
    cap = _parse_nonnegative(raw_maximum, "BATON_RELAY_MAX_GEN/--max-generation")
    return parent + 1, cap


def resolve_provider(requested=None):
    requested = requested or os.environ.get("BATON_RELAY_PROVIDER", "auto")
    requested = requested.lower()
    if requested not in PROVIDERS:
        raise ValueError("BATON_RELAY_PROVIDER must be one of: %s" %
                         ", ".join(PROVIDERS))
    if requested != "auto":
        return requested
    if os.environ.get("BATON_RELAY_COMMAND_JSON"):
        return "custom"
    available = [name for name in ("codex", "claude") if shutil.which(name)]
    if len(available) == 1:
        return available[0]
    if not available:
        raise FileNotFoundError(
            "auto provider found neither 'codex' nor 'claude'; install one or set "
            "BATON_RELAY_PROVIDER/BATON_RELAY_COMMAND_JSON")
    raise ValueError(
        "auto provider found both Codex and Claude Code; choose explicitly with "
        "--provider codex or --provider claude")


def _json_argv(name, required):
    raw = os.environ.get(name, "")
    if not raw:
        if required:
            raise ValueError("%s is required for the custom provider" % name)
        return None
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise ValueError("%s must be a JSON array: %s" % (name, exc))
    if (not isinstance(value, list) or not value or
            not all(isinstance(item, str) and item for item in value)):
        raise ValueError("%s must be a non-empty JSON array of non-empty strings" % name)
    return value


def _expand_custom(argv, root, baton, prompt):
    replacements = {"{root}": str(root), "{baton}": str(baton), "{prompt}": prompt}
    expanded = [replacements.get(item, item) for item in argv]
    if "{prompt}" not in argv:
        expanded.append(prompt)
    return expanded


def build_adapter(provider, root, baton, prompt, model):
    root = os.path.realpath(root)
    if provider == "claude":
        permission = os.environ.get("BATON_RELAY_PERMISSION_MODE", "")
        common = (["--model", model] if model else [])
        interactive = ["claude"] + common
        if permission:
            interactive += ["--permission-mode", permission]
        interactive.append(prompt)
        headless = ["claude", "-p"] + common
        if permission:
            headless += ["--permission-mode", permission]
        headless.append(prompt)
        return {
            "provider": provider,
            "interactive": interactive,
            "headless": headless,
            "headless_safe": bool(permission),
            "model": model or "inherited from Claude Code config",
            "wait_warning": (None if permission else
                             "! NO PERMISSION MODE — Claude may wait at trust or approval."),
            "permission_summary": permission or "interactive approvals",
        }
    if provider == "codex":
        # Baton handoffs default to an explicit read-only sandbox instead of
        # inheriting a potentially broader user configuration.
        sandbox = os.environ.get("BATON_RELAY_SANDBOX", "") or "read-only"
        approval = os.environ.get("BATON_RELAY_APPROVAL_POLICY", "")
        if sandbox and sandbox not in CODEX_SANDBOXES:
            raise ValueError("BATON_RELAY_SANDBOX must be one of: %s" %
                             ", ".join(CODEX_SANDBOXES))
        if approval and approval not in CODEX_APPROVALS:
            raise ValueError("BATON_RELAY_APPROVAL_POLICY must be one of: %s" %
                             ", ".join(CODEX_APPROVALS))
        common = ["-C", root]
        if model:
            common += ["--model", model]
        common += ["--sandbox", sandbox]
        if approval:
            common += ["--ask-for-approval", approval]
        interactive = ["codex"] + common + [prompt]
        # In Codex CLI 0.146, approval policy is a top-level option, not an `exec`
        # option. Keep all shared options before the subcommand so the generated
        # unattended command is accepted by the real parser.
        headless = ["codex"] + common + ["exec", prompt]
        wait_warning = ("! CODEX INTERACTIVE — attach for login prompts."
                        if approval == "never" else
                        "! CODEX INTERACTIVE — attach for login or approval prompts.")
        return {
            "provider": provider,
            "interactive": interactive,
            "headless": headless,
            "headless_safe": True,
            "model": model or "inherited from Codex config",
            "wait_warning": wait_warning,
            "permission_summary": "sandbox=%s, approvals=%s" % (
                sandbox, approval or "Codex default"),
        }
    if provider == "custom":
        interactive_raw = _json_argv("BATON_RELAY_COMMAND_JSON", required=True)
        headless_raw = _json_argv("BATON_RELAY_HEADLESS_COMMAND_JSON", required=False)
        interactive = _expand_custom(interactive_raw, root, baton, prompt)
        headless = (_expand_custom(headless_raw, root, baton, prompt)
                    if headless_raw else None)
        return {
            "provider": provider,
            "interactive": interactive,
            "headless": headless,
            "headless_safe": headless is not None,
            "model": "controlled by custom command",
            "wait_warning": "! CUSTOM INTERACTIVE RECEIVER — attach for prompts.",
            "permission_summary": "controlled by custom command",
        }
    raise ValueError("unsupported provider: %s" % provider)


def _command_available(command):
    executable = command[0]
    if os.path.dirname(executable):
        return os.path.isfile(executable) and os.access(executable, os.X_OK)
    return shutil.which(executable) is not None


def _prune(relay_dir):
    cutoff = time.time() - 7 * 24 * 3600
    for path in relay_dir.iterdir():
        if path.is_file() and (path.name.startswith("baton-") or
                               path.name.startswith("launch-baton-")):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass


def _append_log(root, generation, maximum, session, baton, backend, provider, pid=None):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fields = [stamp, "relay", "gen=%s/%s" % (generation, maximum),
              "session=%s" % session, "baton=%s" % baton,
              "backend=%s" % backend, "provider=%s" % provider]
    if pid is not None:
        fields.append("pid=%s" % pid)
    with open(Path(root) / ".baton" / "batons.log", "a", encoding="utf-8") as fh:
        fh.write("\t".join(fields) + "\n")


def _tmux_spawn(tmux, root, session, command, log):
    exists = subprocess.run(
        [tmux, "has-session", "-t", "=" + session],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if exists.returncode == 0:
        raise FileExistsError("tmux session '%s' already exists" % session)
    subprocess.run(
        [tmux, "new-session", "-d", "-s", session, "-c", root,
         *command], check=True,
    )
    subprocess.run(
        [tmux, "pipe-pane", "-o", "-t", session,
         "cat >> %s" % shlex.quote(str(log))],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _detached_spawn(command, root, log, env):
    output = open(log, "ab", buffering=0)
    kwargs = {
        "cwd": root,
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": output,
        "stderr": subprocess.STDOUT,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) |
            getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    else:
        kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(command, **kwargs)
    finally:
        output.close()
    return process.pid


def _depth_refusal(adapter, generation, maximum):
    print("baton relay: chain depth cap reached (generation %s > %s)." %
          (generation, maximum), file=sys.stderr)
    print(format_command(adapter["interactive"]))
    return 3


def spawn(root, baton, adapter, generation, maximum):
    if generation > maximum:
        return _depth_refusal(adapter, generation, maximum)

    relay_dir = Path(root) / ".baton" / "relay"
    relay_dir.mkdir(parents=True, exist_ok=True)
    _prune(relay_dir)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", Path(root).name).strip("-") or "project"
    session = "baton-%s-%s-g%s-%s-%s" % (
        slug, adapter["provider"], generation,
        datetime.now().strftime("%H%M%S"), os.getpid())
    log = relay_dir / (session + ".log")
    env = dict(os.environ, BATON_RELAY_GEN=str(generation),
               BATON_RELAY_MAX_GEN=str(maximum),
               BATON_RELAY_PROVIDER=adapter["provider"])

    tmux = shutil.which("tmux")
    if tmux:
        if not _command_available(adapter["interactive"]):
            print("baton relay: %s executable is unavailable: %s" % (
                adapter["provider"], adapter["interactive"][0]), file=sys.stderr)
            return 7
        try:
            _tmux_spawn(tmux, os.path.realpath(root), session,
                        adapter["interactive"], log)
        except FileExistsError as exc:
            print("baton relay: %s" % exc, file=sys.stderr)
            return 6
        except (OSError, subprocess.CalledProcessError) as exc:
            print("baton relay: tmux failed: %s" % exc, file=sys.stderr)
            return 7
        _append_log(root, generation, maximum, session, baton, "tmux",
                    adapter["provider"])
        print("baton relay: successor started.\n")
        print("  provider   %s" % adapter["provider"])
        print("  backend    tmux")
        print("  session    %s" % session)
        print("  generation %s of %s" % (generation, maximum))
        print("  model      %s" % adapter["model"])
        print("  policy     %s" % adapter["permission_summary"])
        print("  detail     %s" % baton_tier(baton))
        print("  cwd        %s" % root)
        print("  baton      %s" % baton)
        print("  log        %s" % log)
        print("\n  watch it   tmux attach -t %s" % session)
        if adapter["wait_warning"]:
            print("\nWILL WAIT FOR YOU:\n  %s" % adapter["wait_warning"])
        return 0

    headless = adapter["headless"]
    if not headless or not adapter["headless_safe"]:
        print("baton relay: no tmux and the %s provider has no explicitly safe "
              "headless configuration; refusing to detach a process that may wait "
              "invisibly." % adapter["provider"], file=sys.stderr)
        print(format_command(adapter["interactive"]))
        return 4
    if not _command_available(headless):
        print("baton relay: %s executable is unavailable: %s" % (
            adapter["provider"], headless[0]), file=sys.stderr)
        return 7
    try:
        pid = _detached_spawn(headless, os.path.realpath(root), log, env)
    except OSError as exc:
        print("baton relay: detached spawn failed: %s" % exc, file=sys.stderr)
        return 7
    _append_log(root, generation, maximum, session, baton, "detached-headless",
                adapter["provider"], pid)
    print("baton relay: successor started.\n")
    print("  provider   %s" % adapter["provider"])
    print("  backend    detached-headless")
    print("  pid        %s" % pid)
    print("  generation %s of %s" % (generation, maximum))
    print("  model      %s" % adapter["model"])
    print("  policy     %s" % adapter["permission_summary"])
    print("  cwd        %s" % root)
    print("  baton      %s" % baton)
    print("  log        %s" % log)
    print("\n  This backend is non-interactive; monitor the log above.")
    return 0


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Validate and relay the current Baton")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--print", dest="mode", action="store_const", const="print",
                       help="print the interactive receiver command (default)")
    modes.add_argument("--headless", dest="mode", action="store_const", const="headless",
                       help="print the non-interactive receiver command")
    modes.add_argument("--exec", dest="mode", action="store_const", const="exec",
                       help="replace this process with the interactive receiver")
    modes.add_argument("--spawn", dest="mode", action="store_const", const="spawn",
                       help="start an attachable or safe detached receiver")
    modes.add_argument("--manifest", dest="mode", action="store_const", const="manifest",
                       help="print a validated JSON launch manifest for a host app")
    parser.set_defaults(mode="print")
    parser.add_argument("--provider", choices=PROVIDERS,
                        help="receiver adapter (or BATON_RELAY_PROVIDER)")
    parser.add_argument("--parent-generation", type=int,
                        help="parent generation for app-hosted relays")
    parser.add_argument("--max-generation", type=int,
                        help="override the chain-depth cap")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        root, baton = load_baton()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (baton_gate.BatonRootError, baton_gate.BatonPointerError) as exc:
        print("baton relay: %s" % exc, file=sys.stderr)
        return 5
    ok, lint_output = lint_baton(baton)
    if not ok:
        print("baton relay: '%s' failed mechanical validation — refusing to relay."
              % baton, file=sys.stderr)
        if lint_output:
            print(lint_output, file=sys.stderr)
        return 5
    if not baton_gate.baton_is_valid(baton, expected_root=root):
        print("baton relay: '%s' is invalid or belongs to a different repository."
              % baton, file=sys.stderr)
        return 5
    try:
        provider = resolve_provider(args.provider)
        generation, maximum = relay_position(args.parent_generation, args.max_generation)
        prompt = relay_prompt(baton, generation, maximum)
        model = os.environ.get("BATON_RELAY_MODEL", "")
        adapter = build_adapter(provider, root, baton, prompt, model)
    except ValueError as exc:
        print("baton relay: %s" % exc, file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print("baton relay: %s" % exc, file=sys.stderr)
        return 7

    if args.mode == "manifest":
        if generation > maximum:
            return _depth_refusal(adapter, generation, maximum)
        print(json.dumps({
            "schema_version": 1,
            "provider": provider,
            "root": os.path.realpath(root),
            "baton": str(baton),
            "prompt": prompt,
            "generation": generation,
            "maximum_generation": maximum,
            "detail": baton_tier(baton),
        }, sort_keys=True))
        return 0
    if args.mode == "headless":
        if not adapter["headless"]:
            print("baton relay: provider has no headless command; set "
                  "BATON_RELAY_HEADLESS_COMMAND_JSON", file=sys.stderr)
            return 2
        print(format_command(adapter["headless"]))
        return 0
    if args.mode == "print":
        print(format_command(adapter["interactive"]))
        return 0
    if args.mode == "exec":
        command = adapter["interactive"]
        if not _command_available(command):
            print("baton relay: cannot start %s; executable unavailable: %s" %
                  (provider, command[0]), file=sys.stderr)
            return 7
        try:
            if os.name == "nt":
                return subprocess.call(command, cwd=os.path.realpath(root))
            os.chdir(os.path.realpath(root))
            os.execvp(command[0], command)
        except OSError as exc:
            print("baton relay: cannot start %s: %s" % (provider, exc), file=sys.stderr)
            return 7
    return spawn(root, baton, adapter, generation, maximum)


if __name__ == "__main__":
    sys.exit(main())
