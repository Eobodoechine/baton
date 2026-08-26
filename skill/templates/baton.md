# BATON — {{TOPIC}} (cut {{YYYY-MM-DD HH:MM}})
Chain: {{N}} / Parent: {{PARENT_PATH_OR_none}}
Detail tier: {{teaching|brief}}   # a DETAIL budget, not a model choice
Card: .baton/PROJECT_CARD.md @ {{CARD_HASH8}}
Trust rule: This file is a summary. Anything tagged [S] is summary-derived —
verify it against the repo before acting on it.

## 1. DO THIS NOW
Run: {{THE ONE COMMAND}}
Expected: {{THE LITERAL STRING TO LOOK FOR}}

## 2. WHERE YOU ARE — invariant check
Run: git -C {{REPO}} log --oneline -1
Expected: starts with {{SHA8}}
Run: shasum -a 256 {{REPO}}/.baton/PROJECT_CARD.md | cut -c1-8
Expected: {{CARD_HASH8}}
If either does not match: STOP. Reply "invariant mismatch: <what you saw>" and do
nothing else.

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
