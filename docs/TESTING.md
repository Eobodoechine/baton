# Baton testing strategy

The acceptance target is behavior across operating systems, not a single-machine test
count. All core paths use Python 3.9+ and the standard library; wrappers are tested
separately from the core.

## Test layers

| Layer | What it proves | Runs in CI |
|---|---|---|
| Unit | token accounting, locked state transitions, v2 headers, fingerprints, command quoting | yes |
| Component | status JSON, installer merge/backup/removal, opt-in/override, linter failures | yes |
| Offline integration | due→Stop→v2 baton→fake launch→receipt, safe pickup, fake tmux/custom retry | yes |
| Platform contract | Python 3.9 and 3.13 on macOS, Linux, and Windows | yes |
| Live acceptance | real Codex and Claude receivers, host-app task creation, trust/permission prompts, attachable tmux, native Windows headless run | manual |
| Research eval | Baton versus prose receiver performance | manual and potentially paid |

## Required coverage

Critical decision outcomes have stronger targets than raw line coverage:

- Every relay exit code (0–7) has an offline test or a documented live-only case.
- Codex, Claude, and custom command construction are tested without starting a model;
  `auto` is tested for one receiver, two-receiver ambiguity, and no-receiver failure.
- Every untrusted path input is tested: forged session id, outside pointer, symlink,
  missing target, invalid baton, and headings quoted in comments or fences.
- Every installer outcome is tested: link, link-unavailable copy, idempotent rerun,
  existing-owner-directory refusal, malformed-JSON refusal, backup, unrelated-hook
  preservation, disable-with-wiring-retained, uninstall, POSIX quoting, and Windows
  quoting.
- The runtime covers clean/staged/unstaged/mixed/renamed/deleted/untracked/symlink and
  submodule fingerprints; `.baton/` changes must not affect the fingerprint.
- Stop covers `stop_hook_active`, three continuation attempts, valid-baton/no-receipt,
  matching receipt completion, and a concurrent duplicate-hook transition.
- A manifest v2 includes deterministic handoff identity, baton hash, checkout root,
  fingerprint, successor title, receipt argv, backend capability, and manual fallback.
- Status must parse as JSON for paths containing whitespace, quotes where the platform
  allows them, and Windows separators.
- A resolved due cycle must not immediately re-arm in the same session.
- No automated test starts a paid model or a real successor.

## Commands

```sh
python -m pip install pytest
python -m pytest -q -p no:cacheprovider
python -m compileall -q hooks evals scripts install.py
```

On POSIX systems:

```sh
bash -n install.sh scripts/baton_next.sh skill/scripts/baton_status.sh evals/*.sh
shellcheck install.sh scripts/baton_next.sh skill/scripts/baton_status.sh evals/*.sh
```

## Manual release acceptance

Before calling a release portable, record each result separately:

1. Codex Desktop: trigger the three-identical-tool detector, allow Stop continuation,
   verify one visible successor in the same checkout reads the baton first, then retain
   its returned task-ID receipt.
2. Codex CLI: repeat and retain exactly one successor process/session receipt.
3. Claude Code: repeat and retain exactly one successor tmux/headless receipt.
4. Custom adapter: run the same handoff twice and prove it launches once.
5. Unsupported backend: prove one exact manual command and no success receipt.
6. Cross-platform: macOS, Linux, and Windows install/status/hook settings plus the
   platform-specific CLI paths in a clean account/container.
7. Reinstall/update from a marked-copy installation and confirm owner files are not
   overwritten.
8. Run a real successor only with explicit authorization for any paid model usage.

Green offline CI is source-level portability evidence. It is not proof that a real
Codex task, Claude session, tmux backend, or native Windows host completed a handoff.
