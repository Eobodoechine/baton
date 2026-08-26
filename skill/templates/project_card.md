# PROJECT CARD — {{PROJECT NAME}} ({{ROOT PATH}})

card_version: 1
updated: {{YYYY-MM-DD}}

The **stable** layer: how work is done here, regardless of what task is in flight.
Changes only when the process changes. The volatile layer is `.baton/BATON.md`.

This card is the *executable* companion to the project's `CLAUDE.md` — literal
commands with literal expected output, not narrative. Do not restate `CLAUDE.md`.

## Purpose

{{One or two sentences. What this project is.}}

## Verify commands

| What | Command | Expected |
|---|---|---|
| {{Full suite}} | {{command}} | {{exit 0 / literal output}} |
| {{One file}} | {{command}} | {{expected}} |
| {{Build / typecheck}} | {{command}} | {{expected}} |

{{Name the exact interpreter/runtime if a bare one resolves wrong. This has cost
real cycles before.}}

## Paths

- {{dir}} — {{what lives there}}

## Standing rules

1. {{Rule, positively framed.}}
2. {{Rule.}}

## Always-true gotchas

- {{Trap that is true in this project regardless of task.}}

## Reference

- {{doc path}} — {{what it is}}
