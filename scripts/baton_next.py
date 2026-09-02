#!/usr/bin/env python3
"""Cross-platform Baton relay.

The validation and command-building path is standard-library Python. tmux remains the
preferred attachable backend when present. Without tmux, `--spawn` can use a detached
headless process only when an explicit permission mode is configured; otherwise it
prints a safe manual command and exits 4.
"""

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

(Baton relay generation {generation} of {maximum}. Cutting a baton at the end of this
session will spawn generation {next_generation}; at {maximum} the chain stops and waits
for a human.)""".format(
        path=path, generation=generation, maximum=maximum,
        next_generation=generation + 1,
    )


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


def _append_log(root, generation, maximum, session, baton, backend, pid=None):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fields = [stamp, "relay", "gen=%s/%s" % (generation, maximum),
              "session=%s" % session, "baton=%s" % baton,
              "backend=%s" % backend]
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
         format_command(command, windows=False)], check=True,
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


def spawn(root, baton, model):
    raw_generation = os.environ.get("BATON_RELAY_GEN", "0")
    raw_maximum = os.environ.get("BATON_RELAY_MAX_GEN", "5")
    if not raw_generation.isdigit() or not raw_maximum.isdigit():
        print("baton relay: BATON_RELAY_GEN/MAX_GEN must be integers", file=sys.stderr)
        return 2
    generation = int(raw_generation) + 1
    maximum = int(raw_maximum)
    prompt = relay_prompt(baton, generation, maximum)
    manual = ["claude"] + (["--model", model] if model else []) + [prompt]
    if generation > maximum:
        print("baton relay: chain depth cap reached (generation %s > %s)." %
              (generation, maximum), file=sys.stderr)
        print(format_command(manual))
        return 3

    relay_dir = Path(root) / ".baton" / "relay"
    relay_dir.mkdir(parents=True, exist_ok=True)
    _prune(relay_dir)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", Path(root).name).strip("-") or "project"
    session = "baton-%s-g%s-%s-%s" % (
        slug, generation, datetime.now().strftime("%H%M%S"), os.getpid())
    log = relay_dir / (session + ".log")
    permission = os.environ.get("BATON_RELAY_PERMISSION_MODE", "")
    env = dict(os.environ, BATON_RELAY_GEN=str(generation),
               BATON_RELAY_MAX_GEN=str(maximum))
    interactive = ["claude"] + (["--model", model] if model else [])
    if permission:
        interactive += ["--permission-mode", permission]
    interactive.append(prompt)

    tmux = shutil.which("tmux")
    if tmux:
        try:
            _tmux_spawn(tmux, os.path.realpath(root), session, interactive, log)
        except FileExistsError as exc:
            print("baton relay: %s" % exc, file=sys.stderr)
            return 6
        except (OSError, subprocess.CalledProcessError) as exc:
            print("baton relay: tmux failed: %s" % exc, file=sys.stderr)
            return 7
        _append_log(root, generation, maximum, session, baton, "tmux")
        print("baton relay: successor started.\n")
        print("  backend    tmux")
        print("  session    %s" % session)
        print("  generation %s of %s" % (generation, maximum))
        print("  model      %s" % (model or "inherited from Claude Code config"))
        print("  detail     %s" % baton_tier(baton))
        print("  cwd        %s" % root)
        print("  baton      %s" % baton)
        print("  log        %s" % log)
        print("\n  watch it   tmux attach -t %s" % session)
        if not permission:
            print("\nWILL WAIT FOR YOU:\n  ! NO PERMISSION MODE — the successor may wait at an approval prompt.")
        return 0

    if not permission:
        print("baton relay: no tmux and BATON_RELAY_PERMISSION_MODE is unset; "
              "refusing to detach a process that may wait invisibly.", file=sys.stderr)
        print(format_command(manual))
        return 4
    headless = ["claude", "-p"] + (["--model", model] if model else []) + [
        "--permission-mode", permission, prompt]
    try:
        pid = _detached_spawn(headless, root, log, env)
    except OSError as exc:
        print("baton relay: detached spawn failed: %s" % exc, file=sys.stderr)
        return 7
    _append_log(root, generation, maximum, session, baton, "detached-headless", pid)
    print("baton relay: successor started.\n")
    print("  backend    detached-headless")
    print("  pid        %s" % pid)
    print("  generation %s of %s" % (generation, maximum))
    print("  model      %s" % (model or "inherited from Claude Code config"))
    print("  cwd        %s" % root)
    print("  baton      %s" % baton)
    print("  log        %s" % log)
    print("\n  This backend is non-interactive; monitor the log above.")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = argv[0] if argv else "--print"
    if mode not in ("--print", "--headless", "--exec", "--spawn"):
        print("usage: baton_next.py [--print|--headless|--exec|--spawn]", file=sys.stderr)
        return 2
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
    model = os.environ.get("BATON_RELAY_MODEL", "")
    prompt = "Read %s and execute it. Follow it exactly; do not expand scope." % baton
    command = ["claude"] + (["--model", model] if model else []) + [prompt]
    if mode == "--headless":
        print(format_command(["claude", "-p"] + command[1:]))
        return 0
    if mode == "--print":
        print(format_command(command))
        return 0
    if mode == "--exec":
        try:
            if os.name == "nt":
                return subprocess.call(command)
            os.execvp(command[0], command)
        except OSError as exc:
            print("baton relay: cannot start claude: %s" % exc, file=sys.stderr)
            return 7
    return spawn(root, baton, model)


if __name__ == "__main__":
    sys.exit(main())
