#!/bin/bash
# Best lr per variant from the grid (AR 8e-3, diffusion 4e-3): seeds 1,2 (seed 0 comes from the grid),
# then a 4x-longer budget diagnostic for both variants (seed 0).
cd "$(dirname "$0")"
run(){ o=results/$1; [ -f $o.json ] || python stage_a.py train --mode $2 --lr $3 --seed $4 --steps $5 --out $o.json > $o.log 2>&1; }
export -f run
(run ar_lr8e-3_s1 ar 8e-3 1 1500; run ar_lr8e-3_s2 ar 8e-3 2 1500; run long_ar_lr8e-3_s0 ar 8e-3 0 6000) &
(run diff_lr4e-3_s1 diff 4e-3 1 1500; run diff_lr4e-3_s2 diff 4e-3 2 1500; run long_diff_lr4e-3_s0 diff 4e-3 0 6000) &
wait
