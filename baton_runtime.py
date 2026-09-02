#!/usr/bin/env python3
"""Portable persistence and repository-state primitives for Baton.

This module deliberately has no third-party dependencies and no host-specific
imports.  It is the only place that knows where Baton owns configuration,
state, locks, and receipts.  Hook adapters and launcher adapters must treat
all values read from here as data, never as shell fragments.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, Iterator, Optional, Tuple


SCHEMA_VERSION = 1
SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def checkout_dir() -> Path:
    return Path(__file__).resolve().parent


def runtime_home(home: Optional[Path] = None) -> Path:
    """Return the Baton-owned storage directory.

    BATON_HOME is intentionally an override for tests and advanced deployments;
    normal users always get ~/.baton.  ``home`` exists for installers/tests that
    need to operate on an explicit temporary home without mutating the process
    environment.
    """
    if home is not None:
        return Path(home).expanduser().resolve() / ".baton"
    override = os.environ.get("BATON_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home().expanduser().resolve() / ".baton"


def legacy_config_path(home: Optional[Path] = None) -> Path:
    return (Path(home).expanduser().resolve() if home is not None else Path.home()) / ".baton-config"


def config_path(home: Optional[Path] = None) -> Path:
    return runtime_home(home) / "config.json"


def default_config(base_dir: Optional[Path] = None) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "base_dir": str((base_dir or checkout_dir()).expanduser().resolve()),
        "auto_handoff": False,
        "soft_ratio": 0.70,
        "hard_ratio": 0.80,
        "max_stop_attempts": 3,
        "agents": {
            "codex": {"enabled": False, "provider": "codex"},
            "claude": {"enabled": False, "provider": "claude"},
        },
    }


def _copy_default_fields(value: Dict[str, Any], base_dir: Optional[Path] = None) -> Dict[str, Any]:
    default = default_config(base_dir)
    if not isinstance(value, dict):
        return default
    result = default
    for key in ("schema_version", "base_dir", "auto_handoff", "soft_ratio",
                "hard_ratio", "max_stop_attempts"):
        if key in value:
            result[key] = value[key]
    incoming_agents = value.get("agents")
    if isinstance(incoming_agents, dict):
        for host in ("codex", "claude"):
            candidate = incoming_agents.get(host)
            if isinstance(candidate, dict):
                result["agents"][host].update({
                    key: candidate[key] for key in ("enabled", "provider")
                    if key in candidate
                })
    # Do not perpetuate a broken schema or impossible threshold into all hooks.
    if result["schema_version"] != SCHEMA_VERSION:
        result["schema_version"] = SCHEMA_VERSION
    if not isinstance(result["base_dir"], str) or not result["base_dir"]:
        result["base_dir"] = str((base_dir or checkout_dir()).resolve())
    for key, fallback in (("soft_ratio", .70), ("hard_ratio", .80)):
        try:
            result[key] = float(result[key])
        except (TypeError, ValueError):
            result[key] = fallback
    if not 0 < result["soft_ratio"] <= result["hard_ratio"] <= 1:
        result["soft_ratio"], result["hard_ratio"] = .70, .80
    try:
        result["max_stop_attempts"] = max(1, int(result["max_stop_attempts"]))
    except (TypeError, ValueError):
        result["max_stop_attempts"] = 3
    for host in ("codex", "claude"):
        result["agents"][host]["enabled"] = bool(result["agents"][host].get("enabled"))
        result["agents"][host]["provider"] = host
    result["auto_handoff"] = bool(result["auto_handoff"])
    return result


def read_legacy_base_dir(home: Optional[Path] = None) -> Optional[str]:
    try:
        for line in legacy_config_path(home).read_text(encoding="utf-8").splitlines():
            if line.startswith("base_dir="):
                value = line.split("=", 1)[1].strip()
                return str(Path(value).expanduser()) if value else None
    except OSError:
        pass
    return None


def load_config(home: Optional[Path] = None, base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Load v1 config, falling back to the legacy base_dir pointer once."""
    path = config_path(home)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        raw = {}
    legacy = read_legacy_base_dir(home)
    if legacy and not raw.get("base_dir"):
        raw["base_dir"] = legacy
    return _copy_default_fields(raw, base_dir=base_dir)


def _chmod_private(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        # Windows ACLs own this concern.  A failed chmod is not a data-loss error.
        pass


def atomic_write_bytes(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".%s." % path.name, dir=str(path.parent))
    try:
        try:
            os.fchmod(fd, mode)
        except OSError:
            pass
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        os.replace(temporary, path)
        _chmod_private(path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, value: Dict[str, Any]) -> None:
    atomic_write_bytes(path, (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8"))


def write_config(config: Dict[str, Any], home: Optional[Path] = None,
                 write_legacy: bool = True) -> Dict[str, Any]:
    normalized = _copy_default_fields(config)
    atomic_write_json(config_path(home), normalized)
    if write_legacy:
        legacy = legacy_config_path(home)
        atomic_write_bytes(legacy, ("base_dir=%s\n" % normalized["base_dir"]).encode("utf-8"))
    return normalized


def session_key(value: Any) -> str:
    raw = str(value or "nosession")
    if not SAFE_KEY_RE.fullmatch(raw) or raw in (".", ".."):
        raw = "session-" + hashlib.sha256(raw.encode("utf-8", "surrogateescape")).hexdigest()[:16]
    return raw


def state_path(host: str, session_id: Any, home: Optional[Path] = None) -> Path:
    return runtime_home(home) / "state" / session_key(host) / (session_key(session_id) + ".json")


def receipt_path(handoff_id: str, home: Optional[Path] = None) -> Path:
    return runtime_home(home) / "receipts" / (session_key(handoff_id) + ".json")


def launch_path(handoff_id: str, provider: str, home: Optional[Path] = None) -> Path:
    return runtime_home(home) / "state" / session_key(provider) / ("handoff-" + session_key(handoff_id) + ".json")


@contextmanager
def session_lock(host: str, session_id: Any, home: Optional[Path] = None) -> Iterator[None]:
    """Cross-platform advisory lock for a single host/session state record."""
    path = state_path(host, session_id, home).with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt  # type: ignore
            fh.seek(0)
            if not fh.read(1):
                fh.write(b"0")
                fh.flush()
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl  # type: ignore
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt  # type: ignore
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl  # type: ignore
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def read_state(host: str, session_id: Any, home: Optional[Path] = None) -> Dict[str, Any]:
    try:
        value = json.loads(state_path(host, session_id, home).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def write_state(host: str, session_id: Any, value: Dict[str, Any],
                home: Optional[Path] = None) -> None:
    atomic_write_json(state_path(host, session_id, home), value)


def update_state(host: str, session_id: Any, changes: Dict[str, Any],
                 home: Optional[Path] = None) -> Dict[str, Any]:
    with session_lock(host, session_id, home):
        state = read_state(host, session_id, home)
        state.update(changes)
        state.setdefault("host", host)
        state.setdefault("session_id", session_key(session_id))
        state["updated_at"] = time.time()
        write_state(host, session_id, state, home)
        return state


def record_error(host: str, session_id: Any, error: str,
                 home: Optional[Path] = None) -> None:
    with session_lock(host, session_id, home):
        state = read_state(host, session_id, home)
        state["last_error"] = str(error)[:1000]
        if state.get("phase") in ("observing", "due", "cutting", "launch_pending"):
            state["phase"] = "failed"
        state["updated_at"] = time.time()
        write_state(host, session_id, state, home)


def auto_enabled(host: str, root: Optional[str] = None,
                 home: Optional[Path] = None) -> bool:
    cfg = load_config(home)
    if not cfg["auto_handoff"] or not cfg["agents"].get(host, {}).get("enabled"):
        return False
    if root and (Path(root) / ".baton" / "AUTO_HANDOFF_DISABLED").exists():
        return False
    return True


def _git(root: str, args: list[str], input_data: Optional[bytes] = None) -> bytes:
    completed = subprocess.run(
        ["git", "-C", root, *args], input=input_data, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args),
                                                   completed.stderr.decode("utf-8", "replace").strip()))
    return completed.stdout


def _pathspec_args() -> list[str]:
    return ["--", ".", ":(exclude).baton"]


def _untracked_digest(root: str) -> bytes:
    paths = _git(root, ["ls-files", "--others", "--exclude-standard", "-z", *_pathspec_args()])
    records = [item for item in paths.split(b"\0") if item]
    result = bytearray()
    for raw in sorted(records):
        relative = os.fsdecode(raw)
        path = Path(root) / relative
        result.extend(b"untracked\0" + raw + b"\0")
        try:
            if path.is_symlink():
                payload = os.fsencode(os.readlink(path))
                result.extend(b"symlink\0" + hashlib.sha256(payload).hexdigest().encode() + b"\0")
            elif path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as fh:
                    for block in iter(lambda: fh.read(128 * 1024), b""):
                        digest.update(block)
                result.extend(b"file\0" + digest.hexdigest().encode() + b"\0")
            else:
                # Git's own status remains in the payload; this records a type change
                # without attempting to follow a directory/special-file tree.
                result.extend(b"other\0")
        except OSError as exc:
            result.extend(("error:%s" % exc.__class__.__name__).encode() + b"\0")
    return bytes(result)


def worktree_state(root: str) -> Dict[str, str]:
    """Return a deterministic fingerprint of all relevant checkout state.

    The inputs deliberately include porcelain bytes and binary diffs separately:
    porcelain captures renames, deletions, modes and submodule status while the
    diffs retain staged/unstaged content.  `.baton/` is excluded because cuts and
    receipts must not invalidate the very handoff they create.
    """
    real_root = os.path.realpath(root)
    head = _git(real_root, ["rev-parse", "HEAD"]).decode("ascii", "replace").strip()
    status = _git(real_root, ["status", "--porcelain=v1", "-z", "--untracked-files=all",
                              "--ignore-submodules=none", *_pathspec_args()])
    staged = _git(real_root, ["diff", "--binary", "--no-ext-diff", "--cached", "--",
                              ".", ":(exclude).baton"])
    unstaged = _git(real_root, ["diff", "--binary", "--no-ext-diff", "--",
                                ".", ":(exclude).baton"])
    digest = hashlib.sha256()
    for label, payload in ((b"head", head.encode("ascii", "replace")),
                           (b"porcelain", status), (b"staged", staged),
                           (b"unstaged", unstaged), (b"untracked", _untracked_digest(real_root))):
        digest.update(label + b"\0" + payload + b"\0")
    return {
        "head": head,
        "worktree": "clean" if not status else "dirty",
        "fingerprint": "sha256:" + digest.hexdigest(),
    }


def file_hash(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(128 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def baton_headers(path: str) -> Dict[str, str]:
    try:
        body = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    result: Dict[str, str] = {}
    for key in ("Baton-Version", "Head", "Worktree", "Worktree-Fingerprint", "Card", "Repo"):
        match = re.search(r"^%s:\s*(.+?)\s*$" % re.escape(key), body, re.M)
        if match:
            result[key] = match.group(1)
    return result


def verify_baton_state(path: str, root: Optional[str] = None) -> Tuple[bool, str]:
    """Validate the version-2 repository invariant encoded in a baton."""
    headers = baton_headers(path)
    version = headers.get("Baton-Version", "1")
    if version == "1":
        return True, "legacy version-1 baton: repository-state fingerprint unavailable"
    if version != "2":
        return False, "unsupported Baton-Version: %s" % version
    head = headers.get("Head", "")
    worktree = headers.get("Worktree", "")
    fingerprint = headers.get("Worktree-Fingerprint", "")
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        return False, "missing or invalid Head header"
    if worktree not in ("clean", "dirty"):
        return False, "missing or invalid Worktree header"
    if not SHA256_RE.fullmatch(fingerprint):
        return False, "missing or invalid Worktree-Fingerprint header"
    checkout = root or headers.get("Repo", "")
    if not checkout or not os.path.isabs(checkout):
        return False, "missing repository root"
    card = headers.get("Card", "")
    card_match = re.search(r"@\s*([0-9a-f]{8})\s*$", card)
    if not card_match:
        return False, "missing or invalid Card pin"
    try:
        card_hash = file_hash(os.path.join(checkout, ".baton", "PROJECT_CARD.md")).split(":", 1)[1][:8]
    except OSError:
        return False, "cannot read pinned PROJECT_CARD.md"
    if card_hash != card_match.group(1):
        return False, "card hash mismatch"
    actual = worktree_state(checkout)
    if actual["head"] != head:
        return False, "HEAD mismatch: baton=%s checkout=%s" % (head, actual["head"])
    if actual["worktree"] != worktree:
        return False, "worktree kind mismatch: baton=%s checkout=%s" % (worktree, actual["worktree"])
    if actual["fingerprint"] != fingerprint:
        return False, "worktree fingerprint mismatch"
    return True, "repository state verified"


def handoff_id(root: str, baton_hash: str, generation: int, provider: str) -> str:
    payload = "\0".join((os.path.realpath(root), baton_hash, str(generation), provider))
    return hashlib.sha256(payload.encode("utf-8", "surrogateescape")).hexdigest()


def read_receipt(handoff: str, home: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(receipt_path(handoff, home).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def successful_receipt(handoff: str, home: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    value = read_receipt(handoff, home)
    return value if value and value.get("status") == "launched" and value.get("handoff_id") == handoff else None


def write_launch_pending(handoff: str, provider: str, value: Dict[str, Any],
                         home: Optional[Path] = None) -> None:
    data = dict(value)
    data.update({"handoff_id": handoff, "provider": provider, "launch_status": "launch_pending",
                 "updated_at": time.time()})
    atomic_write_json(launch_path(handoff, provider, home), data)


def record_receipt(handoff: str, provider: str, backend: str,
                   home: Optional[Path] = None, **extra: Any) -> Dict[str, Any]:
    value: Dict[str, Any] = {
        "schema_version": 1,
        "handoff_id": handoff,
        "status": "launched",
        "provider": provider,
        "backend": backend,
        "recorded_at": time.time(),
    }
    value.update(extra)
    atomic_write_json(receipt_path(handoff, home), value)
    return value
