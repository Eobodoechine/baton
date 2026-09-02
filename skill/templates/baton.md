# BATON — {{TOPIC}} (cut {{YYYY-MM-DD HH:MM}})
Baton-Version: 2
Chain: {{N}} / Parent: {{PARENT_PATH_OR_none}}
Detail tier: {{teaching|brief}}   # a DETAIL budget, not a model choice
Repo: {{ABSOLUTE_PATH_OF_THE_EXACT_CHECKOUT}}
Head: {{40_CHARACTER_CURRENT_HEAD_SHA}}
Worktree: {{clean|dirty}}
Worktree-Fingerprint: sha256:{{64_HEX_CHARACTERS}}
Card: .baton/PROJECT_CARD.md @ {{CARD_HASH8}}
Trust rule: This file is a summary. Anything tagged [S] is summary-derived —
verify it against the repo before acting on it.

<!-- Before filling Head/Worktree/Fingerprint, run:
python {{BATON_BASE_DIR}}/scripts/batonctl.py snapshot --root {{REPO}} -->

## 1. DO THIS NOW
Run: {{THE ONE COMMAND}}
Expected: {{THE LITERAL STRING TO LOOK FOR}}

## 2. WHERE YOU ARE — invariant check
Run: python {{BATON_BASE_DIR}}/scripts/batonctl.py verify-state --root {{REPO}} --baton {{BATON_PATH}}
Expected: repository state verified
This verifies the exact HEAD, pinned card hash, and worktree fingerprint. If it does
not exit 0: STOP. Reply "invariant mismatch: <what you saw>" and do nothing else.

## 3. THE TASK — numbered steps
1. {{Step. Name the exact file and the exact function or lines.}}
2. {{Step.}}
3. Verify: {{command}}
   Expected: {{literal output}}
4. Commit: "{{message}}".
   Verify: git log --oneline -1 shows that message.

## 4. DO NOT RETRY
- Tried: {{approach}} -> failed: {{why}}. Established by {{how}}.
- Tried: {{approach}} -> failed: {{why}}. [S]

## 5. USER'S WORDS (verbatim)
"{{exact quote}}"
{{or the single line: none recorded}}

## 6. RULES THAT BIND THIS TASK
- {{rule from the card that actually applies here}}
- {{at most five, positively framed}}

## 7. STATE (done + verified)
{{What is finished AND green, with the commit SHA. Completed work is recoverable
from git — keep this short.}}

## 8. FILES
- {{absolute path}} — {{one clause on why it matters}}

## 9. GOTCHAS
- {{non-obvious trap that would cost the receiver a cycle}}

## 10. DECISIONS + WHY
{{TEACHING TIER (the default). Why this task, why this approach, what was ruled out
and on what evidence. Write it so a reader with no shared history learns the
reasoning, not just the moves. Omit only at brief tier.}}

## 11. DONE MEANS
{{command}} exits 0 with "{{expected}}", and {{other objective condition}}.
Nothing else is in scope.
REPEAT — DO THIS NOW: {{THE ONE COMMAND, verbatim from section 1}}
