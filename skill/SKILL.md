---
name: baton
description: >
  Session handoff. Cuts a "baton" — a small, self-contained document that lets a
  fresh, contextless session (possibly a different model or platform) continue this work
  exactly where it stopped. Also picks up a baton left by a previous session.
when_to_use: >
  Use when a session is ending, running long, or crossing the context threshold and
  the work is not finished. Triggers on: "cut a baton", "/baton", "hand off this
  session", "write a handoff", "pick up the baton", "continue where we left off",
  or when a BATON DUE notice appears in context.
allowed-tools: Read, Bash, Write
---

# Baton — session handoff

The receiver is a **fresh mind with no shared history** — possibly a different model,
possibly a different kind of intelligence entirely. It has the repo and this document,
and nothing else.

So the job is not "write down what happened." It is **"make every instruction
verifiable, and make the reasoning behind them learnable."** A receiver that can check
each step against reality does not need to trust you; a receiver that understands why
the task is the task can tell when the plan has stopped making sense.

The design once assumed weak receivers decay exponentially in instruction count, and
optimised for terseness. This system's own eval did not reproduce that, so brevity is no
longer the goal — verifiability and explanation are.

---

**STEP -1 — Load the contract (do this before anything else):**

Read `~/.baton-config`. Extract its `base_dir=` line (expand `~`) as `BASE_DIR`.
If the file does not exist, resolve this installed skill: a symlink points into
`<BASE_DIR>/skill`; a copied installation has `.baton-install.json` whose `source`
points there. If neither identifies a checkout, use the local templates only and say
that status, lint, and relay are unavailable. Never guess a base directory.

Read `<BASE_DIR>/SPEC.md` fresh from disk. **That file is the
contract; this skill never restates it.** If it does not exist, fall back to
`templates/baton.md` in this skill directory and continue — the skill works
standalone.

**STEP 0 — Resolve the project and read state:**

Run `<BASE_DIR>/hooks/baton_status.py` with Python 3.9 or newer. It returns JSON:

```json
{"root":"...","current_baton":"...","age_hours":3.2,"card":"...",
 "card_hash":"a3f9c1d2","card_hash_matches":true,"pointer_valid":true,
 "mandatory_sections_filled":true,"due_flag":true,"due_scope":"all_sessions"}
```

Branch on it. `root` is the project root; the two layers live at
`<root>/.baton/PROJECT_CARD.md` (stable) and `<root>/.baton/BATON.md` (volatile).

---

## `cut` — write the baton

**STEP 1 — Run the pre-termination checklist.** Do not cut mid-flight.

- No pending tool calls.
- No background processes owned by this session.
- No uncommitted changes (commit first — the receiver's invariant check pins a SHA).
- No question from the user still unanswered.

If any fails, resolve it first. A baton cut over a dirty tree hands the receiver a
state it cannot verify.

**STEP 2 — Ensure the card exists.** If `<root>/.baton/PROJECT_CARD.md` is missing,
build it from `templates/project_card.md` using the project's `CLAUDE.md` and the
commands you actually ran this session. Show it to the user and get confirmation
before first use — a wrong card poisons every future baton.

If the card exists but you violated or discovered a standing rule this session, say
so and offer `card` (below). Do not silently edit it.

**STEP 3 — Write `<root>/.baton/BATON.md`** from `templates/baton.md`, following the
schema in `SPEC.md`. Include `Repo: <absolute owning repository path>` in the header.
Budget: **5,000 tokens** (`--tier teaching`, the default,
which includes §10 Decisions + Why) or **2,500** (`--tier brief`, §10 omitted, for a
task that genuinely is small).

Tiers are detail budgets, **not** model classes — a tier never picks a model. Write so
that any receiver, any model, any intelligence with no shared history, can both execute
the task and understand why it is the task.

The eight rules that make it work:

1. **One task. Numbered steps. Never a menu.** The receiver must be able to start
   step 1 without asking for direction. If the remaining work needs more than 10
   steps, cut a smaller baton covering the first coherent chunk.
2. **The next action goes first AND last.** §1 and the final line of §11 are the same
   command, verbatim. Late instructions are measurably 1.0–1.5x more likely to be
   dropped, so the load-bearing one occupies both privileged positions.
3. **Every step carries its own literal verify command and literal expected output.**
   Not "check that it works" — the command, and the string to look for.
4. **§11 is a command with an expected exit code, never a self-assessment.** A model
   asked "are you done?" says yes. A model asked to run a command and report the exit
   code cannot.
5. **§5 is quote-or-omit.** Paste the user's exact words or write `none recorded`.
   **Never paraphrase.** A summarizer that invents a user instruction gets it
   executed — this has actually happened (`anthropics/claude-code#46602`).
6. **Tag every summary-derived claim `[S]`.** Anything you did not verify this
   session against the repo. The header Trust Rule tells the receiver to check them.
7. **State conclusions, not evidence.** "Use X because Y failed" — never raw data the
   receiver must reason over to reach the same conclusion.
8. **Positive framing.** "Only edit `foo.py`" beats "don't touch anything else."

§4 (**DO NOT RETRY**) is the highest-value section and is never trimmed. Record every
dead end with *why* it failed and *how* that was established. Without it the next
session re-attempts them — which is the single most expensive thing to rediscover.

§6 holds **at most 5 rules**, digested from the card — only the ones binding *this*
task. Do not copy the card wholesale; that is the whole point of having two layers.

Under budget pressure, trim in this order: §10, §7, §9, §8. Never trim §1–§6 or §11.

**STEP 4 — Verify and archive.** Run
`python <BASE_DIR>/evals/lint_baton.py <root>/.baton/BATON.md`
if it exists. Copy the baton to `<root>/.baton/archive/baton_YYYY-MM-DD_<topic>.md`,
write its absolute path into `<root>/.baton/BATON_CURRENT`, and append a line to
`<root>/.baton/batons.log`.

**STEP 5 — Hand over by starting the successor.** Run
`python <BASE_DIR>/scripts/baton_next.py --spawn`. The detail tier never chooses a
model. The successor inherits the configured model unless `BATON_RELAY_MODEL` is set.
With tmux it launches an attachable session; without tmux it uses a detached headless
backend only when `BATON_RELAY_PERMISSION_MODE` is explicitly set.

Report the backend, relay generation, and either the `tmux attach` line or the detached
PID and log path. Say that the successor is running only after exit 0.

**If the output contains a `WILL WAIT FOR YOU:` block, repeat it verbatim.** An
interactive tmux successor may be parked at trust or approval prompts. A detached
headless relay is never started without an explicit permission mode.

`--spawn` refuses rather than guessing. Read its exit code and relay the reason:

| Exit | Meaning | What to tell the user |
|---|---|---|
| 0 | spawned | session name + `tmux attach -t <name>` |
| 1 | no baton on disk | the cut did not land; do not retry blindly, find out why |
| 2 | invalid root or relay settings | correct the named setting; do not guess |
| 3 | relay depth cap hit | the chain stopped on purpose; it printed the manual command |
| 4 | safe manual fallback required | it printed the command; the user starts it by hand |
| 5 | unsafe pointer or invalid baton | **fix the baton** — do not force the spawn |
| 6 | session name collision | a successor is already running; do not spawn a second |
| 7 | launch backend failed | report the exact error and log path; do not claim it started |

Never work around a refusal by invoking `claude` directly. Each exit above is a
deliberate stop, and exit 5 in particular means an unattended session was about to
inherit a half-written document.

---

## `pickup` — receive a baton

Read `<root>/.baton/BATON_CURRENT`, then the baton it names.

**Run §2's invariant check before touching anything.** If it does not match, STOP and
report the mismatch — do not improvise around it. A failed invariant means the baton
is stale on either code or process, and its steps may now be wrong.

Then execute §3, in order, running each step's verify command. Do not do anything the
baton does not ask for.

---

## `card` — update the stable layer

Edit `<root>/.baton/PROJECT_CARD.md`, bump `card_version`, and update `updated:`.
Do this when the **process** changed — a new verify command, a new standing rule, a
newly discovered always-true gotcha. Not for task state; that belongs in the baton.

Existing batons pin the old hash and will now fail their drift check. That is the
intended behavior: process changed under them.

---

## `status` — report

Run `python <BASE_DIR>/hooks/baton_status.py` and summarize: is a baton pending, is its
pointer safe, how old is it, does the card hash match, and is a cut due. When
`due_scope` is `all_sessions`, say that the due flag is machine-wide rather than
claiming it belongs to this project.

---

## Hard rules

- **Never invent content.** If you cannot verify it, either tag it `[S]` or leave it
  out. An unverified claim in a baton becomes an instruction in the next session.
- **Never write the pass-verdict phrasing** (`verdict:` followed by `pass`) or
  dispatch-role phrases into a baton. `hooks/loop_stop_guard.py` pattern-matches that
  shape. Write "Verifier result — green".
- **Never delete a prior baton.** Archive it.
- **`cut` is idempotent.** Running it twice overwrites `BATON.md` and archives both.
- **The relay has a depth cap.** `BATON_RELAY_MAX_GEN` (default 5) bounds how many
  sessions can hand off to each other without a human. Do not raise it to get past a
  stuck chain — a chain that hit the cap is a chain that is not converging.
