# BATON_SPEC — session handoff contract

**Status: ACTIVE as of 2026-08-25.** This is the canonical spec. The `baton` skill
live-reads this file on every invocation; the skill never duplicates it.

---

## 0. Terminology decree (2026-08-25)

This repo overloaded "handoff" and "continuation" three ways: a doc category
(`session_handoff_*.md`), a design-section title (`orchestrator.md` cookbook item 1),
and the name of a completed build (Codex parity for RUNLOG). That overload is why a
fresh word was chosen.

- The artifact is a **baton**. The event is a **baton cut**. The receiving act is a
  **pickup**.
- `session_handoff_*` and `session_continuation_*` are retired as names for **new**
  files. Existing files are never renamed — this repo is append-only.
- Two ideas from the legacy skeleton carry forward: the *"do not trust this summary
  over the repo"* disclaimer (now the **Trust Rule**) and the numbered context-boot
  list (now **§3**).

## 1. Why two layers

The receiver may be a contextless Haiku-class model. The binding constraint on such a
receiver is **instruction count, not document length**:

- "Curse of Instructions" (openreview `R6q67CDBCH`): prompt-level accuracy(n) =
  per-instruction-accuracy^n. Exponential in the number of simultaneous instructions.
- IFScale (arXiv 2507.11538): frontier models decay **linearly** with instruction
  density; **Claude 3.5 Haiku and Llama-4-Scout decay exponentially, with steep losses
  at low densities.**
- ManyIFEval: at >=3 simultaneous instructions most models fall below 50% joint success.

So standing project rules must not ride in the per-task document. They live one layer
up:

| Layer | File | Changes | Carries |
|---|---|---|---|
| **Stable** | `.baton/PROJECT_CARD.md` | only when process changes | how work is done here: verify commands, paths, standing rules, always-true gotchas |
| **Volatile** | `.baton/BATON.md` | every cut | this task only |

The baton pins the card by content hash — `Card: .baton/PROJECT_CARD.md @ a3f9c1d2`.
If the on-disk hash differs, process drifted under the baton and the receiver's
invariant check fails closed.

The baton also names its owning repository — `Repo: /absolute/path/to/clone`. The
shared resolver anchors linked worktrees to their owning clone and refuses to guess a
directory outside Git. Pickup, status, and relay all use that resolver.

The card is the **executable** layer; the repository's applicable agent instructions
(for example `AGENTS.md`, `CLAUDE.md`, or another designated file) remain the
narrative layer. The card does not restate those files — it states literal commands
with literal expected output.

## 2. Layout

Artifacts live in `.baton/` at the project root. Loop's flat-file convention governs
*docs*; artifacts already live in dirs (`runs/`, `control-plane/`, `worktrees/`), so
this is consistent. Design docs like this one stay flat in `loop-team/`.

```
<project-root>/.baton/
|-- PROJECT_CARD.md                        # stable layer
|-- BATON.md                               # volatile layer, current
|-- BATON_CURRENT                          # one line: active baton path (contained below .baton)
|-- batons.log                             # append-only cut/pickup ledger
`-- archive/baton_YYYY-MM-DD[a-z]_<topic>.md
```

Inside an armed loop run, `cut` additionally hard-links the baton to
`runs/<run-id>/baton.md` so it sits beside `run_log.md`.

## 3. Schema

Haiku tier budget **2,500 tokens**. Frontier raises the cap to **5,000** and unlocks
§10 only. There is **one template**, always written to the weak-receiver floor —
Chroma's Context Rot found focused-beats-long for every model tested, with Claude
models showing the largest gap, so the discipline costs nothing on Opus and is
load-bearing on Haiku.

Ordering is primacy/recency-driven. IFScale measured late instructions as **1.0-1.5x
more likely to be dropped**, so the one next action occupies both privileged
positions: first content block, and repeated verbatim as the final line.

| # | Section | Budget | Mandatory | Trim order |
|---|---|---|---|---|
| 0 | Header + Trust Rule + `Card:` pin + `Repo:` line | 140 | YES | never |
| 1 | `## 1. DO THIS NOW` | 150 | YES | never |
| 2 | `## 2. WHERE YOU ARE — invariant check` | 180 | YES | never |
| 3 | `## 3. THE TASK — numbered steps` (<=10) | 700 | YES | never |
| 4 | `## 4. DO NOT RETRY` | 400 | YES | never |
| 5 | `## 5. USER'S WORDS (verbatim)` | 200 | YES or `none recorded` | never |
| 6 | `## 6. RULES THAT BIND THIS TASK` (<=5) | 200 | YES | never |
| 7 | `## 7. STATE (done + verified)` | 250 | no | 2nd |
| 8 | `## 8. FILES` (<=6, absolute paths) | 150 | no | 4th |
| 9 | `## 9. GOTCHAS` | 200 | no | 3rd |
| 10 | `## 10. DECISIONS + WHY` | frontier only | no | **1st** |
| 11 | `## 11. DONE MEANS` + repeated DO-THIS-NOW | 150 | YES | never |

### Generator rules (enforced by `lint_baton.py`)

1. **Quote-or-omit for §5.** If the exact user quote cannot be pasted, the section
   reads `none recorded`. **Paraphrase is forbidden.** This is the direct defense
   against `anthropics/claude-code#46602`, where a pre-compact summarizer fabricated a
   user instruction that never existed and the next agent executed it across 44 tool
   calls.
2. **`[S]` tag** on any summary-derived claim, plus the header Trust Rule.
3. **Conclusions, not evidence.** "Use X because Y failed" — never raw data the
   receiver must reason over to reach the same conclusion.
4. **Positive framing.** "Only edit `foo.py`" beats "don't touch anything else."
   Anthropic's own guidance is to say what to do rather than what not to do.
5. **Every step carries its own literal verify command and literal expected output.**
6. **§11 is a command with an expected exit code**, never a self-assessment. Anthropic
   documented Sonnet 4.5 "context anxiety" — premature wrap-up — requiring an external
   re-check loop that became unnecessary on Opus 4.5. Verification infrastructure that
   is optional for frontier models is load-bearing for weak ones.
7. **§6 holds at most 5 rules**, digested from the card — only the rules that bind
   *this* task. The card is not copied wholesale.
8. **§3 holds at most 10 numbered steps** at haiku tier. If the work needs more, the
   baton is cut smaller.

### Relationship to `orchestrator.md` cookbook item 1

This **extends**, does not supersede, "Priority-ranked context handoff." That section
defines the *maintenance discipline* — Oga keeps a running priority-ordered summary in
`run_log.md`, ranked `corrections > errors > active work > completed work`. That
summary is the baton's **source material**. The ranking maps onto sections:

| Cookbook tier | Baton sections |
|---|---|
| corrections | §4, §9 |
| errors | §4 |
| active work | §1, §2, §3 |
| completed work | §7 (lowest, second to be trimmed) |

## 4. Worked example

This example is the few-shot given to the *cutter*. Google's small-model guidance is
explicit that examples beat abstract description; keep it in the template.

Note the style rule it demonstrates: it writes "Verifier result — green" rather than
the pass-verdict phrasing that `hooks/loop_stop_guard.py` pattern-matches (see §8).

```markdown
# BATON — planckeck tier-1 hash capture (cut 2026-08-25 16:40)
Chain: 2 / Parent: .baton/archive/baton_2026-08-24a_planckeck.md
Receiver tier: haiku
Repo: /Users/eobodoechine/Claude/loop
Card: .baton/PROJECT_CARD.md @ a3f9c1d2
Trust rule: This file is a summary. Anything tagged [S] is summary-derived —
verify it against the repo before acting on it.

## 1. DO THIS NOW
Run: cd ~/Claude/loop && python3 -m pytest hooks/test_plan_check_credit_output.py -q
Expected: last line contains "2 failed, 41 passed"

## 2. WHERE YOU ARE — invariant check
Run: git -C ~/Claude/loop log --oneline -1
Expected: starts with 8c41f2a
Run: shasum -a 256 ~/Claude/loop/.baton/PROJECT_CARD.md | cut -c1-8
Expected: a3f9c1d2
If either does not match: STOP. Reply "invariant mismatch: <what you saw>" and do
nothing else.

## 3. THE TASK — numbered steps
1. Open ~/Claude/loop/hooks/plan_check_credit_output.py. Only edit the function
   _hash_capture (lines 210-260).
2. Change the digest input to its NFC-normalized form
   (unicodedata.normalize("NFC", s)) before hashing.
3. Verify: python3 -m pytest hooks/test_plan_check_credit_output.py -q
   Expected: "43 passed".
4. Commit: "planckeck: NFC-normalize hash capture input".
   Verify: git log --oneline -1 shows that message.

## 4. DO NOT RETRY
- Tried: normalizing at read time in cod_state.py -> failed: broke 6 unrelated
  fixtures (mixed-encoding fixtures are intentional). Verified by full regression
  run 2026-08-24.
- Tried: utf-8-sig decode -> failed: BOM is not the cause; the two red tests use
  NFD composed accents. [S]

## 5. USER'S WORDS (verbatim)
"Fix it in the hash function itself, don't touch the fixture files."

## 6. RULES THAT BIND THIS TASK
- Run pytest UNPIPED. Piping has masked red exits before.
- Commit after every green micro-step (<=200 changed lines).
- Only edit files under hooks/. Paths under tests/ and gates/ are protected.

## 7. STATE (done + verified)
Tier-1 capture path implemented and green except the 2 unicode cases; commit
8c41f2a; hooks suite otherwise green (Verifier result — green, 2026-08-25 15:55).

## 8. FILES
- ~/Claude/loop/hooks/plan_check_credit_output.py — the only file you edit
- ~/Claude/loop/hooks/test_plan_check_credit_output.py — read-only, the gate

## 9. GOTCHAS
- hooks/__pycache__ goes stale; if imports look wrong, delete it and rerun.

## 11. DONE MEANS
python3 -m pytest hooks/test_plan_check_credit_output.py -q exits 0 with
"43 passed", and the commit exists. Nothing else is in scope.
REPEAT — DO THIS NOW: cd ~/Claude/loop && python3 -m pytest
hooks/test_plan_check_credit_output.py -q  (expect "2 failed, 41 passed")
```

## 5. Cut-point policy

Numbers assume a 200k-class window. Claude Code auto-compaction is believed to fire
near 166k (~83%) — that figure is **third-party reverse-engineered, not confirmed by
Anthropic**. It lives as two module constants in `hooks/baton_gate.py`; if it moves,
that is the whole change.

| Trigger | Threshold | Action |
|---|---|---|
| Soft | 140k context | Finish the current micro-step, then cut at the next green commit |
| Hard | 160k context | Cut immediately; §2 encodes the partial state |
| Stuck | same tool, byte-identical args, 3x consecutive | Cut now |
| Red streak | 2 consecutive Verifier-red iterations on one step | Cut now |

Why 140k and not the folk "128k": the 128k number traces to GPT-4-Turbo's old ceiling,
not to evidence. The evidence-backed rule is ~25-50% of the advertised window (RULER
puts effective context there for most models; NoLiMa found 10 of 12 models claiming
>=128k fall below half their own baseline by 32k tokens). Against a 200k-class
operating window with compaction at ~166k, 140k leaves room to finish a micro-step and
still cut cleanly.

### Pre-termination checklist

Model-executed at cut time. Recorded in the run log, **not** in the baton.

- [ ] No pending tool calls.
- [ ] No background processes owned by this session.
- [ ] No uncommitted changes.
- [ ] No unanswered user question in the last 3 turns.

### What is actually measurable — honest accounting

Stating this plainly rather than implying the system senses more than it does.

| Signal | Detectable? | How |
|---|---|---|
| Context fill | **YES** | Hooks receive `transcript_path`; last assistant `usage` gives `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. Tail-read only. |
| 3x identical tool call | **YES** | 3-deep rolling hash of `(tool_name, args)` in `$LOOP_GATE_DIR/<session>_baton_state.json` |
| Task boundary | **NO** | Model-judged. Anchored to the mechanical proxy that exists: the green micro-step commit `micro_step_gates.py` already forces. The hook raises the flag; the model picks the moment. |
| Goal drift, output quality, unanswered questions | **NO** | Not mechanically detectable. Model-side checklist only. |
| Auto-compact imminence | **NO** | `PreCompact` can neither block compaction nor make the model write. The 160k hard trigger is the proxy; PreCompact only records that compaction happened *without* a baton. |

The model's own estimate of its context usage is unreliable and is never used.

## 6. Automation

`hooks/baton_gate.py` is argv-flag dispatched and may be registered in
`~/.claude/settings.json`. These lifecycle hooks are a Claude Code adapter, not part of
the Baton document contract. Codex and other receivers remain fully functional through
the installed skill and manual status/cut/pickup flow. `install.py` prints guarded
commands for the current platform when Claude is an install target; hooks remain
optional.

> **Trap:** `~/.claude/hooks/{session_init,user_prompt_submit,pre_tool_use}.py` are
> inert duplicates. Nothing references them; the live copies run from the model-router
> plugin manifest. Never wire new behavior there.

| Event | Flag | Behavior |
|---|---|---|
| `PostToolUse` | `--meter` | Measure context; maintain tool-call hash; write `<session>_baton_due` on trigger. Emits nothing. |
| `UserPromptSubmit` | `--nag` | One line when due, once per turn. |
| `Stop` | `--gate` | **Only in armed loop runs** (`$LOOP_GATE_DIR/<session>_target` exists). Blocks up to 3x if no fresh valid baton, then allows and writes `_BATON_MISSING`. |
| `SessionStart` (`startup`, `resume`) | `--pickup` | One <=120-char line if a baton <48h old is pending; consume-once. |
| `SessionStart` (`compact`) | `--post-compact-warn` | Brands the compaction summary untrusted. |
| `PreCompact` (`auto`) | `--compact-marker` | Records the missed baton. Nothing else. |

Every mode fails open on `OSError`. **The machinery may stamp, never summarize** — no
hook ever writes baton prose. That is the `#46602` lesson encoded as an architectural
rule.

### Registration must be existence-guarded

Register every mode as:

```
if [ -f ~/Claude/loop/hooks/baton_gate.py ]; then python3 ~/Claude/loop/hooks/baton_gate.py <flag>; fi
```

Not the bare command. The hook code fails open, but a bare registration does not: if
the file is absent, `python3` exits 2 on "can't open file" and PostToolUse surfaces
that as a *blocking* error, wedging a tool call. Caught in the wild 2026-08-25.

`|| true` is the wrong fix — it would also swallow `--gate`'s intentional exit 2. The
`if` form exits 0 when the file is missing and preserves the exit code when it is not.
`hooks/test_baton_gate.py` asserts both halves.

### The relay (`python scripts/baton_next.py --spawn`)

**Superseded 2026-09-01.** This spec once equated relay with starting an external
`claude`. Relay is a receiver-neutral operation. The core now has built-in Codex and
Claude Code adapters, a custom JSON argv adapter, and a validated JSON manifest for
host applications such as Codex Desktop. Detached custom launches pass argv directly
to the process API. tmux receives the receiver command and its arguments separately,
which uses tmux's direct-execution form rather than `sh -c`. The relay core is Python
3.9+ so validation, path containment, quoting, and exit codes are shared across macOS,
Linux, and Windows. When tmux exists, CLI `--spawn` launches an attachable session.
Without tmux, the adapter must expose a non-interactive path that cannot wait
invisibly.

The relay is wired to **`/baton cut` STEP 5 only**. Session `Stop` does not relay. A
session hands off when a cut was actually asked for, never as a side effect of ending.

| Control | Default | Purpose |
|---|---|---|
| `BATON_RELAY_PROVIDER` | `auto` | `codex`, `claude`, `custom`, or `auto`. Auto selects only when exactly one built-in receiver is installed; it never silently prefers a vendor. |
| `BATON_RELAY_GEN` | unset | Set by the spawner on the child. Absent means human-started, i.e. generation 0. |
| `BATON_RELAY_MAX_GEN` | `5` | Chain depth cap. At the cap `--spawn` refuses and prints the manual command. |
| `BATON_RELAY_MODEL` | unset | Optional model override passed to either built-in receiver. |
| `BATON_RELAY_PERMISSION_MODE` | unset | Claude adapter only; passed through to `--permission-mode`. Required for detached Claude. |
| `BATON_RELAY_SANDBOX` | unset | Codex adapter only; `read-only`, `workspace-write`, or `danger-full-access`. Unset makes Baton pass `read-only` explicitly instead of inheriting user config. |
| `BATON_RELAY_APPROVAL_POLICY` | unset | Codex adapter only; `untrusted`, `on-request`, or `never`. |
| `BATON_RELAY_COMMAND_JSON` | unset | Custom interactive argv as a JSON string array. Exact `{root}`, `{baton}`, and `{prompt}` tokens are replaced. tmux receives each argv value separately. |
| `BATON_RELAY_HEADLESS_COMMAND_JSON` | unset | Custom non-interactive argv; required before a custom receiver may detach without tmux. |

Generation is carried in the child's environment, not on disk, so it **self-resets**: a
human-started session is always generation 0 and cannot inherit a stale counter.

`--spawn` **refuses rather than guesses**, with distinct exit codes: `1` no baton, `2`
invalid settings or ambiguous provider, `3` depth cap, `4` safe manual fallback required, `5` unsafe pointer
or invalid baton, `6` session collision, and `7` backend failure. Every mode runs the
structural linter before starting or printing a receiver command. Each successful spawn
appends a backend-labelled line to `.baton/batons.log`; detached output goes to
`.baton/relay/<session>.log`.

The relay does not weaken the architectural rule. It **starts a receiver and points it
at a file a model wrote**; it never generates baton prose.

`--manifest --provider <name>` runs the same pointer, linter, ownership, settings, and
depth checks and emits a JSON object containing the exact root, baton path, prompt, and
generation. A host app may use that manifest to create a visible task. The host must
claim success only after it receives a task identifier. App-hosted receivers carry the
generation in the prompt and pass it back with `--parent-generation` on the next cut.

**Claude adapter live-tested 2026-08-26** (scratch repo, `claude-haiku-4-5` receiver, real sessions).
The successor read the baton, ran the §2 invariant check *before* anything else, executed
§3, self-verified, and honoured "do not cut a baton". Two blockers surfaced that no dry
run would have shown, and `--spawn` now warns about both:

1. **Folder trust is per-directory and is checked before the prompt is read.** The child
   parks at *"Is this a project you trust?"*. Running `claude` from a parent directory
   does **not** trust the child directory — `Claude/Projects/ai-os` had
   `hasTrustDialogAccepted: false` while `~` had `true`. Cost is one Enter, once per
   project, forever.
2. **An interactive successor can stall at login, trust, or approval.** The relay emits
   an attach warning for interactive providers. A Claude headless fallback is never
   detached unless `BATON_RELAY_PERMISSION_MODE` is explicitly set. Codex uses the
   supported non-interactive `codex exec` surface and explicitly passes `read-only`
   unless the user chooses another sandbox. A custom receiver detaches only
   when a separate headless argv is configured.

Trust is recorded in `~/.claude.json` under the **realpath** of the root
(`/private/tmp/...`, not `/tmp/...`), so `--spawn` normalises the root before both the
trust check and the child's `cd`.

### Portability contract

- Core runtime: Python 3.9+ standard library and Git.
- Supported CI matrix: macOS, Linux, and Windows on the oldest and newest supported
  Python versions.
- Convenience wrappers: Bash on POSIX and PowerShell on Windows. The wrappers contain
  no state or validation logic.
- Optional capability: tmux provides an attachable relay; it is not required for
  status, cut, lint, pickup, manual continuation, or guarded headless relay.
- Platform-specific features must degrade with a named exit code and a manual command,
  never by guessing paths or silently skipping validation.

**Graceful degradation:** with zero hooks wired the skill is fully functional by hand.
Hooks add measurement, nagging, gating, and auto-pickup — nothing else.

## 7. Detail tiers

One template. `--tier` is a budget knob, not a template switch — two templates would
drift apart, and include/exclude flags multiply the *cutter's* own instruction load.

**Tiers are detail budgets, not model classes.** A tier never selects a model; the relay
inherits whatever model is configured (§6). The former names `haiku`/`frontier` welded
those two ideas together — cutting a "haiku baton" silently also meant *spawning* a
haiku — and survive only as aliases.

| Tier | Cap | Effect |
|---|---|---|
| `teaching` (default, alias `frontier`) | 5,000 tok | §10 Decisions + Why included; fuller §7 |
| `brief` (alias `haiku`) | 2,500 tok | Trim order enforced; <=10 steps; §10 omitted |

**The default is `teaching`.** A baton should let any receiver — any model, any
intelligence, with no shared history — both *execute* the task and *understand why it is
the task*. Write §4 and §10 so a reader learns the reasoning, not just the moves.

The old default optimised for minimum instruction count against weak receivers, on the
premise of exponential instruction-density decay in Haiku-class models. **This system's
own eval did not reproduce that** (0/3 substantive delta, `claude-haiku-4-5`). With the
premise unsupported, terseness buys little, while a receiver that acts without
understanding is the expensive failure. Choose `brief` only when the task genuinely is.

The `Receiver tier:` header records which was used.

## 8. Style rules that exist for safety

- Never write the pass-verdict phrasing (`verdict:` immediately followed by `pass`) in
  a baton, a card, or any skill prompt. `hooks/loop_stop_guard.py` regex-matches that
  shape on tool_use blocks to decide whether a turn was a Verifier dispatch requiring a
  run log. Write "Verifier result — green" instead. `hooks/test_baton_gate.py` holds a
  fixture proving baton-shaped text neither trips nor satisfies that gate.
- Never write dispatch-role phrases (`role: coder`, `verifier plan-check`) in baton
  prose for the same reason.

## 9. Changelog

## 2026-08-25 — initial spec

Created. Two-layer model, 2,500-token haiku floor, 140k/160k triggers, six hook modes,
`.baton/` layout. Research basis: RULER, NoLiMa, Chroma Context Rot, IFScale, Curse of
Instructions, Anthropic long-running-agent harness guidance, `claude-code#46602`.

## 2026-08-26 — Eval result: comprehension claim not supported

`evals/baton/run_hard_eval.sh` (6 unstated facts, both arms given all six,
claude-haiku-4-5, n=3) returned a **substantive delta of 0/3**. Well-written prose
carrying the same facts matched the baton on every substantive criterion.

The schema's demonstrated value is therefore narrower than section 1 claims:

- **Shown:** halt-on-stale. The §2 invariant check stops a receiver dead when HEAD or
  the card hash moved, with zero edits. Prose has no equivalent; the control arm never
  checked anything.
- **Shown:** mechanical enforceability — lintable, gate-able, non-emptiness-checkable.
- **NOT shown:** that structure improves weak-model comprehension over good prose.
  IFScale measured Claude 3.5 Haiku; Haiku 4.5 did not reproduce it here.

Section 1's reasoning is retained as the design's *motivation*, not as a verified
result. Raise the fact count to 12-15 and re-run before treating the hypothesis as
either confirmed or dead.
