#!/usr/bin/env bash
# run_hard_eval.sh — the discriminating eval.
#
# Six facts are in play that the repo does not state. BOTH arms receive all six: the
# baton as structure, the control as prose. Same information, different presentation.
# That is what makes the delta a measurement of the SCHEMA rather than of content.
#
#   TRIALS=5 ./run_hard_eval.sh
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
PYBIN=${PYBIN:-$HOME/Claude/loop/.venv/bin/python}
MODEL=${MODEL:-claude-haiku-4-5}
TRIALS=${TRIALS:-5}
OUT=${OUT:-/tmp/baton_hard_$(date +%Y%m%d_%H%M%S)}
mkdir -p "$OUT"

b_sub=0; c_sub=0; b_full=0; c_full=0

for i in $(seq 1 "$TRIALS"); do
  for arm in baton control; do
    dir="$OUT/${arm}_${i}"
    "$HERE/make_fixture_hard.sh" "$dir" >/dev/null
    if [ "$arm" = "control" ]; then
      sha=$(git -C "$dir" log --format=%h -1)
      sed "s/{{SHA}}/$sha/g" "$HERE/control_notes_hard.md" > "$dir/NOTES.md"
      rm -f "$dir/.baton/BATON.md"
      prompt="Read NOTES.md and continue the work it describes."
    else
      prompt="Read .baton/BATON.md and execute it. Follow it exactly; do not expand scope."
    fi
    ( cd "$dir" && claude -p "$prompt" --model "$MODEL" \
        --output-format stream-json --verbose --permission-mode acceptEdits \
        --allowedTools Read Edit Write Bash Glob Grep \
        > "$OUT/${arm}_${i}.jsonl" 2>"$OUT/${arm}_${i}.err" )
    "$PYBIN" "$HERE/grade_receiver.py" "$OUT/${arm}_${i}.jsonl" "$dir" --hard \
        > "$OUT/${arm}_${i}.verdict.json" 2>&1
    rc=$?
    grep -q '"substantive_pass": true' "$OUT/${arm}_${i}.verdict.json" && {
      [ "$arm" = baton ] && b_sub=$((b_sub+1)) || c_sub=$((c_sub+1)); }
    [ $rc -eq 0 ] && { [ "$arm" = baton ] && b_full=$((b_full+1)) || c_full=$((c_full+1)); }
    echo "  trial $i $arm: substantive=$(grep -q '"substantive_pass": true' "$OUT/${arm}_${i}.verdict.json" && echo PASS || echo FAIL)"
  done
done

cat <<S | tee "$OUT/SUMMARY.txt"

model:   $MODEL   trials: $TRIALS
                    substantive   full
baton:              $b_sub/$TRIALS           $b_full/$TRIALS
control:            $c_sub/$TRIALS           $c_full/$TRIALS
SUBSTANTIVE DELTA:  $((b_sub - c_sub))/$TRIALS
output:  $OUT

The substantive delta is the result. Both arms held the same six facts; only the
presentation differed. A delta at or near 0 means the schema is not earning its
2,500-token discipline -- report that and change the schema.
S
