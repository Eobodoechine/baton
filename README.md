# baton

Session handoff for Claude Code. A **baton** is a small, self-contained document that
lets a fresh, contextless session pick up unfinished work exactly where the last one
stopped — and, optionally, start that session for you automatically.

Built for the case where a long session is about to hit its context ceiling and the
work isn't done.

## Quick start

```sh
git clone https://github.com/Eobodoechine/baton.git
cd baton && ./install.sh
```

`install.sh` symlinks `skill/` into `~/.claude/skills/baton` and prints the hook config
for you to paste. It refuses to clobber an existing install, and it never writes to your
`settings.json` itself, because a bad hook registration wedges tool calls and that is not
a thing to do to someone's config unasked.

Hooks are entirely optional. With zero hooks wired the skill works fully by hand.

Then, in any project, from a Claude Code session that is running long:

```
/baton card      once per project, describe how work is done here
/baton cut       write the handoff and start the successor session
/baton pickup    from the fresh session, resume exactly where you stopped
/baton status    is a baton pending, how old, does the card hash still match
```

Run `/baton card` first. Everything else works better once the stable layer exists.

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

There is no config file, and that is deliberate. The thing you customise is the **stable
layer**, `.baton/PROJECT_CARD.md`, one per project. It is the executable companion to
your `CLAUDE.md`: literal commands with literal expected output, not narrative.

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

Rewrite the template's wording freely. It is a starting shape, not a schema, and nothing
parses those headings.

## The relay (auto-spawn)

`/baton cut` ends by running `scripts/baton_next.sh --spawn`, which starts the successor
as a **detached tmux session** — it begins immediately, survives the parent terminal
closing, and stays attachable:

```
tmux attach -t baton-<project>-g1-143022    # watch or interject; ctrl-b d to detach
tmux kill-session -t baton-<project>-g1-143022
```

Chain depth is capped by `BATON_RELAY_MAX_GEN` (default 5). The generation rides in the
child's *environment*, not on disk, so it self-resets: a session you start by hand is
always generation 0 and cannot inherit a stale counter. At the cap, `--spawn` refuses
and prints the manual command.

`--spawn` refuses rather than guesses: `1` no baton, `3` depth cap, `4` no tmux (prints
the command instead), `5` baton missing a mandatory section, `6` session-name collision.

**Two things park a successor before it does any work**, and `--spawn` warns about both:

1. **Folder trust is per-directory.** The child stops at Claude Code's *"Is this a
   project you trust?"* prompt before it reads the baton. Running `claude` from a parent
   directory does **not** trust a subdirectory. One Enter, once per project.
2. **Without a permission mode, it stalls at the first approval prompt.** Set
   `BATON_RELAY_PERMISSION_MODE=acceptEdits` for an unattended relay. Unset is the
   default, because a relay that waits is safer than one that doesn't.

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
- The relay works end to end, including unattended.

It is **not** established that the baton format improves weak-model comprehension. That
was tested fairly and the result was null. The eval is in this repo so you can rerun it.

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
hooks/test_baton_gate.py 42 tests
scripts/baton_next.sh    the relay
evals/                   linter, fixtures, receiver grader, the null-result eval
```

## Architectural rule

**The machinery may stamp, never summarize.** No hook here ever writes baton prose.
[`anthropics/claude-code#46602`](https://github.com/anthropics/claude-code/issues/46602)
documents a pre-compact summarizer fabricating a user instruction that never existed,
which the next agent then executed across 44 tool calls. Machine-generated summary text
is the failure mode. Only a model writes batons; hooks measure and flag.

## Provenance

Extracted from a private loop-engineering framework. One coupling remains and is
intentional: `hooks/baton_gate.py`'s Stop gate reads `$LOOP_GATE_DIR` to detect an armed
loop run, and blocks only there. Outside that, it is a silent meter plus a one-line nag.
One test skips when `loop_stop_guard.py` is absent, which is the normal standalone case.

## Tests

```sh
python3 -m pytest hooks/test_baton_gate.py -q
```

## License

MIT
