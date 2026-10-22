#!/bin/bash
cd "$(dirname "$0")"
for W in "64 32 2" "128 64 4"; do
  set -- $W; GD=$1; LD=$2; GH=$3
  for V in float ternary; do
    OUT=results/tern/s1_${V}_g${GD}.json
    [ -f "$OUT" ] && continue
    FLAG=""; [ "$V" = ternary ] && FLAG="--ternary"
    python3 train_patch2.py --steps 1200 --gd $GD --ld $LD --gh $GH --lh 4 $FLAG --seed 1 \
      --ckpt results/tern/s1_${V}_g${GD}.ck --out "$OUT" >> results/tern/s1_${V}_g${GD}.log 2>&1
  done
done
echo done > results/tern/S1_DONE
