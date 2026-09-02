# Baton skill

Baton hands unfinished work to a fresh, contextless session through a mechanically
checkable document. The stable project rules live in `.baton/PROJECT_CARD.md`; the
current task lives in `.baton/BATON.md` and pins the card by hash.

## Commands

| Command | Action |
|---|---|
| `/baton cut [--tier teaching\|brief]` | Validate, archive, and relay one task |
| `/baton pickup` | Validate and read the pending baton |
| `/baton card` | Update the stable layer after a process change |
| `/baton status` | Report pending baton, age, card drift, pointer validity, and due state |

Tiers control detail, not the receiver model. `teaching` is the 5,000-token default;
`brief` is the 2,500-token budget for genuinely small tasks.

## Platform support

The core requires Python 3.9+ and Git and runs on macOS, Linux, and Windows. POSIX
`.sh` and Windows PowerShell wrappers are conveniences; status, validation,
installation, and relay logic live in Python.

tmux is optional. With tmux, an auto-spawned successor is attachable. Without tmux,
Baton can start a detached headless successor only when
`BATON_RELAY_PERMISSION_MODE` is explicitly set; otherwise it prints the manual
command and refuses an invisible wait.

Hooks are optional. They add context measurement, due notices, a bounded Stop gate in
armed Loop runs, and safe pickup announcements. Manual cut and pickup remain usable
without hooks.

## Contract

The authoritative schema and exit codes are in `SPEC.md` at the installed checkout.
Mandatory headings and the `Repo:`, `Card:`, and `Trust rule:` header fields are
structural. Examples inside comments or fenced code do not satisfy them.
