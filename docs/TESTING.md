# Baton testing strategy

The acceptance target is behavior across operating systems, not a single-machine test
count. All core paths use Python 3.9+ and the standard library; wrappers are tested
separately from the core.

## Test layers

| Layer | What it proves | Runs in CI |
|---|---|---|
| Unit | token accounting, session-id containment, structural parsing, exit-code mapping, command quoting | yes |
| Component | status JSON, installer behavior, linter failures, due-cycle reset | yes |
| Offline integration | safe pointer pickup, relay validation, fake tmux, detached fake receiver, fixture lint | yes |
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
  existing-owner-directory refusal, POSIX quoting, and Windows quoting.
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

1. macOS: Codex and Claude install targets, status, guarded hook command, Codex Desktop
   manifest/task creation, tmux relay, and manual fallback.
2. Linux: both CLI adapters, custom argv, install, status, tmux, and no-tmux paths in a
   clean user account or container.
3. Windows: `install.py`, PowerShell wrappers, status, invalid-pointer refusal, and
   detached headless relay with a non-production fixture.
4. Reinstall/update from a marked-copy installation and confirm owner files are not
   overwritten.
5. Run a real successor only with explicit authorization for any paid model usage.

Green offline CI is source-level portability evidence. It is not proof that a real
Codex task, Claude session, tmux backend, or native Windows host completed a handoff.
