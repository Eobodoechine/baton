# baton — session handoff

Cuts a small, self-contained document that lets a fresh session — possibly a
Haiku-class model with no context — continue work exactly where it stopped.

## Two layers

| Layer | File | Changes |
|---|---|---|
| Stable | `<project>/.baton/PROJECT_CARD.md` | only when the process changes |
| Volatile | `<project>/.baton/BATON.md` | every cut |

The baton pins the card by hash. If they drift apart, the receiver's invariant check
fails closed and it halts rather than improvising.

This split exists for a measured reason: weak models' accuracy falls off exponentially
in the *number* of simultaneous instructions, so standing rules must not ride in the
per-task document.

## Commands

| Command | Does |
|---|---|
| `/baton cut [--tier haiku\|frontier]` | Write the baton, archive it, print the successor command |
| `/baton pickup` | Read the pending baton and continue |
| `/baton card` | Update the stable layer after a process change |
| `/baton status` | Report: pending baton, age, card drift, whether a cut is due |

## Without hooks

Fully functional by hand. `cut` writes the files; `pickup` reads them. Hooks only add
measurement (`--meter`), the due notice (`--nag`), the Stop gate in armed loop runs
(`--gate`), and auto-announcement at session start (`--pickup`).

## The one manual step

Claude Code cannot spawn the successor session from a hook. Run:

```bash
scripts/baton_next.sh
```

## Contract

`SPEC.md` at the root of this repo. The skill live-reads it; this README does not
restate it.
