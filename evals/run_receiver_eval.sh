#!/usr/bin/env bash
# run_receiver_eval.sh — the honest end-to-end check.
#
# Hands a real baton to a real Haiku-class model with no context, and compares it
# against a CONTROL arm handed the raw run-log tail instead. The deliverable metric
# is the success DELTA. If the delta is zero, the 2,500-token discipline is not
# earning its keep and the schema is wrong.
#
#   TRIALS=5 ./run_receiver_eval.sh
#
# Costs real API calls. Nothing here runs on its own.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
PYBIN=${PYBIN:-$HOME/Claude/loop/.venv/bin/python}
MODEL=${MODEL:-claude-haiku-4-5}
TRIALS=${TRIALS:-5}
OUT=${OUT:-/tmp/baton_eval_$(date +%Y%m%d_%H%M%S)}
mkdir -p "$OUT"

run_arm() {           # run_arm <arm> <trial> <prompt> <extra-grade-flag>
  local arm=$1 trial=$2 prompt=$3 flag=${4:-}
  local dir="$OUT/${arm}_${trial}"
  "$HERE/make_fixture.sh" "$dir" >/dev/null

  # The control arm gets the same facts as unstructured narrative -- what a session
  # would actually leave behind without a baton.
  if [ "$arm" = "control" ]; then
    rm -f "$dir/.baton/BATON.md"
    sed -n '1,200p' "$HERE/control_notes.md" > "$dir/NOTES.md"
    sed -i '' "s/{{SHA}}/$(git -C "$dir" log --format=%h -1)/g" "$dir/NOTES.md" 2>/dev/null || true
  fi

  ( cd "$dir" && claude -p "$prompt" \
      --model "$MODEL" \
      --output-format stream-json --verbose \
      --permission-mode acceptEdits \
      --allowedTools Read Edit Write Bash Glob Grep \
      > "$OUT/${arm}_${trial}.jsonl" 2>"$OUT/${arm}_${trial}.err" )

  "$PYBIN" "$HERE/grade_receiver.py" "$OUT/${arm}_${trial}.jsonl" "$dir" "$flag" \
      > "$OUT/${arm}_${trial}.verdict.json" 2>&1
  local rc=$?
  local sub
  sub=$(grep -c '"substantive_pass": true' "$OUT/${arm}_${trial}.verdict.json" || true)
  [ "${sub:-0}" -gt 0 ] && eval "${arm}_sub=\$(( ${arm}_sub + 1 ))"
  echo "  $arm trial $trial: $([ $rc -eq 0 ] && echo PASS || echo FAIL) (substantive: $([ "${sub:-0}" -gt 0 ] && echo yes || echo no))"
  return $rc
}

baton_pass=0; control_pass=0; stale_pass=0
baton_sub=0; control_sub=0

for i in $(seq 1 "$TRIALS"); do
  echo "trial $i"
  run_arm baton   "$i" "Read .baton/BATON.md and execute it. Follow it exactly; do not expand scope." && baton_pass=$((baton_pass+1))
  run_arm control "$i" "Read NOTES.md and continue the work it describes." && control_pass=$((control_pass+1))
done

# Stale arm: the baton is valid but HEAD moved underneath it. The receiver must halt.
echo "stale-baton arm"
dir="$OUT/stale_1"
"$HERE/make_fixture.sh" "$dir" >/dev/null
( cd "$dir" && echo "# drift" >> README.md && git add -A && git commit -qm "unrelated drift" )
( cd "$dir" && claude -p "Read .baton/BATON.md and execute it. Follow it exactly; do not expand scope." \
    --model "$MODEL" --output-format stream-json --verbose \
    --permission-mode acceptEdits --allowedTools Read Edit Write Bash Glob Grep \
    > "$OUT/stale_1.jsonl" 2>"$OUT/stale_1.err" )
"$PYBIN" "$HERE/grade_receiver.py" "$OUT/stale_1.jsonl" "$dir" --stale > "$OUT/stale_1.verdict.json" 2>&1 \
  && { stale_pass=1; echo "  stale trial 1: PASS (halted)"; } || echo "  stale trial 1: FAIL (did not halt)"

cat <<SUMMARY | tee "$OUT/SUMMARY.txt"

model:   $MODEL
trials:  $TRIALS
                    full    substantive-only
baton:              $baton_pass/$TRIALS     $baton_sub/$TRIALS
control:            $control_pass/$TRIALS     $control_sub/$TRIALS
delta:              $((baton_pass - control_pass))/$TRIALS     $((baton_sub - control_sub))/$TRIALS
stale:   $stale_pass/1 (must halt on invariant mismatch)
output:  $OUT

Read the SUBSTANTIVE delta, not the full one. The full delta counts protocol criteria
(the invariant check) that the control arm was never asked to satisfy, so it flatters
the baton. Only the substantive delta is evidence that the schema transfers knowledge
better than prose does.

A substantive delta of 0 means the fixture is too easy to discriminate, not that the
baton is worthless -- make the task harder (more steps, more dead ends, a distractor
file) before concluding anything.
SUMMARY
