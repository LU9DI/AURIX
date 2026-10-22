#!/bin/bash
# float vs ternario (BitNet b1.58 simulado), mesmo numero de passos, 3 larguras. Retoma de checkpoint se reiniciado.
cd "$(dirname "$0")"
STEPS=1200
for W in "64 32 2" "128 64 4" "256 128 8"; do
  set -- $W; GD=$1; LD=$2; GH=$3
  for V in float ternary; do
    OUT=results/tern/${V}_g${GD}.json
    [ -f "$OUT" ] && continue
    FLAG=""; [ "$V" = ternary ] && FLAG="--ternary"
    python3 train_patch2.py --steps $STEPS --gd $GD --ld $LD --gh $GH --lh 4 $FLAG --seed 0 \
      --ckpt results/tern/${V}_g${GD}.ck --out "$OUT" >> results/tern/${V}_g${GD}.log 2>&1
  done
done
echo done > results/tern/ALL_DONE
