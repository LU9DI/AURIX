#!/bin/bash
# Tuning grid (seed 0): lr per variant. Skips finished runs (resume-safe).
cd "$(dirname "$0")"
for mode in ar diff; do for lr in 1e-3 2e-3 4e-3; do echo "$mode $lr"; done; done | \
xargs -P2 -L1 bash -c 'o=results/$0_lr$1_s0.json; [ -f $o ] || python stage_a.py train --mode $0 --lr $1 --seed 0 --steps 1500 --out $o > results/$0_lr$1_s0.log 2>&1'
