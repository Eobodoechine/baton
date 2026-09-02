# baton

Session handoff for coding agents. A **baton** is a small, self-contained document that
lets a fresh, contextless session pick up unfinished work exactly where the last one
stopped — and, optionally, start that session for you automatically.

Built for the case where a long session is about to hit its context ceiling and the
work isn't done.

## Quick start

Requires Git and Python 3.9 or newer. Clone the repo, then run the platform-neutral
installer:

```sh
git clone https://github.com/Eobodoechine/baton.git
cd baton
python3 install.py --agent codex    # macOS/Linux, Codex
python3 install.py --agent claude   # macOS/Linux, Claude Code
py -3 install.py --agent codex      # Windows, Codex
```

`install.sh` and `install.ps1` are convenience wrappers around the same Python
installer. Omit `--agent` to install into every locally detected supported agent, or
use `--agent all` explicitly.

The installer links `skill/` into `~/.codex/skills/baton`,
`~/.claude/skills/baton`, or both. If directory symlinks are unavailable (common on
Windows without Developer Mode), it creates a clearly marked copy instead. It refuses
to clobber an existing install and never edits agent settings. Installation creates
`~/.baton/config.json` plus the legacy `~/.baton-config` pointer, but automatic handoff
starts **off** and no host setting changes are made.

Codex mode does not require a Claude installation or account and does not invoke the
Claude adapter.

Hooks are optional. With zero hooks wired the skill works fully by hand. To explicitly
enable automation, run one of these commands after installing:

```sh
python scripts/batonctl.py auto enable --agent codex
python scripts/batonctl.py auto enable --agent claude
python scripts/batonctl.py auto disable --project /absolute/project/path
python scripts/batonctl.py status --json
python scripts/batonctl.py doctor --agent codex --json
```

`auto enable` atomically merges only Baton-owned entries, retaining unrelated hooks and
making a backup before its first write. `auto disable` leaves those inert entries in
place; `batonctl hooks uninstall --agent ...` is the separate explicit removal command.

Codex requires a one-time trust review for non-managed hooks. After `auto enable`:

1. Start a **new Codex session** in any Git checkout.
2. Run `/hooks`.
3. Open the user hook source `~/.codex/hooks.json` and review the Baton commands. Each
   Baton command must point at the checkout where you installed Baton.
4. Mark the Baton entries trusted and enabled. Codex binds trust to the current hook
   definition, so repeat this review after a hook command changes.
5. Run one harmless tool call, then run
   `python scripts/batonctl.py doctor --agent codex --json`. `hook_runs_seen: true`
   proves a Baton hook executed; `/hooks` remains the authority for persisted trust.

Do not keep an old Baton skill under another name inside `~/.codex/skills/`: Codex
indexes it as a second skill. Move backups outside the skills directory (for example,
under `~/.baton/backups/`) or remove them after confirming `~/.codex/skills/baton`
points at the intended checkout.

Then, in any project, ask the installed skill to run one of these actions:

| Action | Codex | Claude Code | Purpose |
|---|---|---|---|
| card | `$baton card` | `/baton card` | Once per project, describe how work is done here |
| cut | `$baton cut` | `/baton cut` | Write the handoff and start the successor session |
| pickup | `$baton pickup` | `/baton pickup` | Resume from the fresh session |
| status | `$baton status` | `/baton status` | Check pending state, age, and card hash |

Run the `card` action first. Everything else works better once the stable layer exists.

## The two layers

Standing project rules do not ride in the per-task document. They live one layer up:

| Layer | File | Changes | Carries |
|---|---|---|---|
| **Stable** | `.baton/PROJECT_CARD.md` | only when the *process* changes | how work is done here: verify commands, paths, standing rules, always-true gotchas |
| **Volatile** | `.baton/BATON.md` | every cut | this task only |

The baton pins the card by content hash (`Card: .baton/PROJECT_CARD.md @ a3f9c1d2`). If
the on-disk hash differs, the process drifted under the baton and the receiver's
invariant check fails closed.

The design rationale is in [`SPEC.md`](SPEC.md), which is the contract — the skill
live-reads it and never restates it.

## What it does

```
/baton cut       write the baton, archive it, and start the successor session
/baton pickup    receive a baton left by a previous session
/baton card      update the stable layer (process changed)
/baton status    is a baton pending, how old, does the card hash still match
```

## Making it yours

There is no per-project configuration language. The installer writes only
`~/.baton-config`, a location pointer to this checkout. The thing you customise is the
**stable layer**, `.baton/PROJECT_CARD.md`, one per project.

`/baton card` scaffolds it from [`skill/templates/project_card.md`](skill/templates/project_card.md).
Fill in four things and the rest of the system gets sharper:

| Section | What to put | Why it earns its place |
|---|---|---|
| **Verify commands** | The exact command and its exact expected output | A receiver that can check its own work does not have to trust you. Name the literal interpreter if a bare one resolves wrong; that has cost real cycles. |
| **Paths** | Which directory holds what | Stops a fresh session guessing at your layout |
| **Standing rules** | How work is done here, framed positively | These are the rules that outlive any one task |
| **Always-true gotchas** | Traps true in this project regardless of task | The things you would say out loud to a new teammate on day one |

Keep task detail out of the card. Anything true only of the work currently in flight
belongs in `.baton/BATON.md`, which is rewritten on every cut. The split is the whole
design: the card changes when your *process* changes, the baton changes every handoff.

The baton pins the card by content hash, so if the card moved underneath a pending
baton, the receiver fails closed rather than working off stale instructions. That is
also the failure mode to expect first if a pickup refuses.

Rewrite the template's prose freely, but keep the mandatory headings and header fields.
Pickup and relay parse them structurally and ignore lookalikes inside comments or fenced
examples.

## Automatic handoff

Automatic handoff has four independently observable steps:

1. **Detection:** `PostToolUse` measures a known context window or detects three
   identical tool calls; `PreCompact(auto)` is the reliable no-token fallback.
2. **Model-authored cut:** `Stop` returns one bounded continuation instruction. The
   model—not a hook—writes and validates the Baton-Version 2 prose.
3. **Host launch:** the current host uses its own adapter to start exactly one successor.
4. **Receipt:** success exists only after `~/.baton/receipts/<handoff-id>.json` records
   the matching provider/backend/task or session.

The `.baton/AUTO_HANDOFF_DISABLED` marker opts one project out. Automatic dirty-tree
handoffs reuse the same checkout and verify the exact HEAD, card hash, and worktree
fingerprint before the successor edits anything; Baton never creates an automatic WIP
commit.

| Environment | Automatic result | Current acceptance status |
|---|---|---|
| Codex Desktop | Visible successor task in the same saved checkout | **verified on macOS** (task-ID receipt) |
| Codex CLI | One successor CLI/tmux session plus receipt | **verified on macOS** (tmux receipt) |
| Claude Code | One successor CLI/tmux session plus receipt | **verified on macOS** (tmux receipt) |
| Custom adapter | One deduplicated launch after implementing the contract below | **verified on macOS** with a fake argv adapter and real tmux |
| Unsupported backend | Validated baton plus one exact manual command | **verified on macOS** with no launch and no success receipt |

These entries were accepted on macOS on 2026-09-02. They do not claim native Linux or
Windows live acceptance; the cross-platform CI contract remains separate. CI is
offline and never invokes a paid receiver. A host/OS combination moves to **verified**
only after it produces a fresh matching receipt and the successor proves it read and
verified the baton before editing.

### The relay

The relay is receiver-neutral. Built-in adapters support Codex and Claude Code, and a
shell-free JSON argv adapter supports other agents. Detached launches pass argv
directly to the process API; attachable tmux launches pass the command and each
argument separately, using tmux's direct-execution form rather than `sh -c`. Choose
explicitly when more than one supported receiver is installed:

```sh
python scripts/baton_next.py --spawn --provider codex
python scripts/baton_next.py --spawn --provider claude
```

`--provider auto` is the default. It selects the only installed built-in receiver. If
both are present it exits 2 and asks you to choose instead of silently favoring one.

Inside Codex Desktop, the skill first validates the baton with
`--manifest --provider codex`, then searches existing visible tasks for the exact
manifest `handoff_id`. It creates a local-checkout task only when none exists and runs
the manifest `receipt_recording_argv` with the returned task ID. Outside the desktop
app, `--spawn` uses the Codex or Claude CLI. A task creation without its receipt is not
success.

When tmux is available, CLI relay starts the successor as a detached, attachable tmux
session:

```
tmux attach -t baton-<project>-g1-143022    # watch or interject; ctrl-b d to detach
tmux kill-session -t baton-<project>-g1-143022
```

Chain depth is capped by `BATON_RELAY_MAX_GEN` (default 5). The generation rides in the
child's *environment*, not on disk, so it self-resets: a session you start by hand is
always generation 0 and cannot inherit a stale counter. At the cap, `--spawn` refuses
and prints the manual command.

Without tmux, behavior depends on the receiver's supported non-interactive surface:

- Codex uses the official non-interactive `codex exec` command. Its default sandbox is
  set explicitly to `read-only` by Baton so a broader user configuration cannot leak
  into the successor. Set `BATON_RELAY_SANDBOX=workspace-write` only when the baton
  must edit, and optionally set `BATON_RELAY_APPROVAL_POLICY=never` for a fully
  unattended run.
- Claude Code starts a detached headless receiver only when
  `BATON_RELAY_PERMISSION_MODE` is explicitly set. Otherwise it prints the manual
  command and exits 4 rather than hiding a waiting approval prompt.
- A custom receiver needs both `BATON_RELAY_COMMAND_JSON` and, for detached use,
  `BATON_RELAY_HEADLESS_COMMAND_JSON`. Each is a JSON array of argv strings; Baton does
  not run the receiver command through a shell. Exact `{root}`, `{baton}`, and
  `{prompt}` tokens are replaced. If `{prompt}` is absent, the prompt is appended.

`BATON_RELAY_MODEL` is an optional model override for either built-in receiver. The
baton's `teaching` or `brief` tier still controls document detail only; it never picks a
provider or model.

Relay exits are stable: `1` no baton, `2` invalid or ambiguous relay settings, `3` depth cap, `4`
manual fallback required, `5` unsafe or invalid baton, `6` session collision, and `7`
backend launch failure.

Interactive receivers can park before doing work, and `--spawn` prints a
`WILL WAIT FOR YOU:` warning when that is possible:

1. **Claude folder trust is per-directory.** The child stops at Claude Code's *"Is this a
   project you trust?"* prompt before it reads the baton. Running `claude` from a parent
   directory does **not** trust a subdirectory. One Enter, once per project.
2. **An interactive receiver may stall at login or an approval prompt.** For Claude, set
   `BATON_RELAY_PERMISSION_MODE=acceptEdits` for an unattended relay. Unset is the
   default. For Codex, use its explicit sandbox and approval controls above. A relay
   that waits visibly is safer than one that waits invisibly.

## What was measured, and what did not hold

The design is built on published findings that weak models degrade *exponentially* in
instruction count where frontier models degrade linearly ("Curse of Instructions",
IFScale, ManyIFEval). That is the reason for the two-layer split.

**The discriminating eval did not reproduce that.** `evals/run_hard_eval.sh` (6 unstated
facts, both arms given all six, `claude-haiku-4-5`, 3 trials) returned a **substantive
delta of 0/3**: a control arm carrying the same facts as well-written prose matched the
baton on every substantive criterion. IFScale measured Claude 3.5 Haiku; this is Haiku
4.5, and the effect did not show up.

So claim only what is shown:

- The §2 invariant check makes a receiver **halt on stale state**. The stale arm halts
  with zero edits, every time; prose has no equivalent.
- The format is **mechanically lintable and gate-able** (`evals/lint_baton.py`).
- A historical Claude adapter probe is not evidence for this release. Every host in
  the acceptance matrix needs its own fresh matching live receipt; offline command
  construction is not a substitute.

It is **not** established that the baton format improves weak-model comprehension. That
was tested fairly and the result was null. The eval is in this repo so you can rerun it.

### Adapter contract

A custom adapter receives the manifest's `handoff_id`, exact checkout root, validated
baton path/hash/fingerprint, successor title, prompt, manual command, and receipt argv
(replace its literal `{task_id}` only with the provider-returned identifier).
It must look up its deterministic successor identity before creating anything, recover a
same-handoff collision as success, preserve an unrelated collision as exit 6, and run
the receipt argv only after the provider returns a real task/process/session identifier.
Manual fallback is never a receipt.

## Install detail

`./install.sh` is covered in Quick start above. Hooks add context metering, a due-baton
nag, a Stop gate, and auto-pickup announcements. Register each mode existence-guarded,
see [`SPEC.md`](SPEC.md) §6 for why a bare registration wedges a tool call when the file
is absent.

## Layout

```
SPEC.md                  the contract; the skill live-reads it
skill/                   the /baton skill (SKILL.md, templates, status script)
hooks/baton_gate.py      context meter, nag, Stop gate, pickup announcer
hooks/baton_status.py    portable JSON status
scripts/baton_next.py    cross-platform relay core
install.py               cross-platform Codex/Claude installer
evals/                   linter, fixtures, receiver grader, the null-result eval
```

## Architectural rule

**The machinery may stamp, never summarize.** No hook here ever writes baton prose.
[`anthropics/claude-code#46602`](https://github.com/anthropics/claude-code/issues/46602)
documents a pre-compact summarizer fabricating a user instruction that never existed,
which the next agent then executed across 44 tool calls. Machine-generated summary text
is the failure mode. Only a model writes batons; hooks measure and flag.

## Provenance

The temporary legacy parser still reads old `$LOOP_GATE_DIR` registrations so existing
unhosted users are not broken. New Codex/Claude hooks always pass `--host` and use only
the Baton-owned runtime under `~/.baton/`; no private Loop marker is part of the public
automatic-handoff path.

## Tests

```sh
python -m pip install pytest
python -m pytest -q -p no:cacheprovider
```

CI runs the offline suite on macOS, Linux, and Windows with Python 3.9 and 3.13.
Paid receiver evaluations are deliberately separate and never run in CI. See
[`docs/TESTING.md`](docs/TESTING.md).

## License

MIT
