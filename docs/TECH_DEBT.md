# Baton technical-debt register

Priority uses `(Impact + Risk) × (6 − Effort)`, with each input scored 1–5. Higher is
more urgent.

| Priority | Debt | Type | Impact | Risk | Effort | Score | Business reason |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | Public source, Loop runtime, and installed skill are separate copies | Architecture | 5 | 5 | 3 | 30 | A fix can be green in one surface while users keep running another |
| 2 | Context thresholds depend on third-party behavior and fixed 200k assumptions | Code | 3 | 3 | 2 | 24 | A vendor change can make handoffs too early or too late |
| 3 | No-tmux relay is non-interactive | Infrastructure | 3 | 3 | 3 | 18 | Windows and minimal Linux users can continue work, but cannot attach to the session |
| 4 | Real relay acceptance is platform-dependent and manual | Test | 4 | 4 | 4 | 16 | Offline process simulation cannot prove prompts, terminals, or vendor CLI behavior |
| 5 | Due state is machine-global when no session id is available | Architecture | 2 | 2 | 3 | 12 | Status can report that some session is due without naming the project |
| 6 | Installation is source-checkout based rather than a versioned package | Dependency | 3 | 3 | 4 | 12 | Updates and rollback require managing a checkout or marked copy |
| 7 | Receiver-comprehension advantage remains unproven | Test | 2 | 2 | 5 | 4 | The safety protocol is useful, but marketing must not claim a measured quality lift |

## Phased remediation

### Phase 0 — safety and portability

Keep pointer containment, structural linting, portable status JSON, guarded install,
explicit relay exits, and the OS matrix as release blockers. These changes fit beside
feature work because each is independently testable.

### Phase 1 — one distributable source

Choose one canonical Baton package. Make Loop and the installed skill consume it by
versioned link or package reference. Add a drift command that prints the source SHA and
runtime SHA without modifying either checkout.

### Phase 2 — live platform receipts

Run the manual release matrix in `docs/TESTING.md` and retain host, Python, Git,
receiver, backend, task/session ID, command, exit code, and log location. Keep live
acceptance distinct from CI.

### Phase 3 — calibration and research

Make context thresholds configurable with safe defaults and a status explanation.
Rerun paid receiver research only with an approved budget and a harder fixture; report
protocol safety separately from substantive task-quality delta.
