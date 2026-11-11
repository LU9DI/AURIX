#!/bin/bash
# Curva de escala: 5 larguras, cabecas de dimensao fixa (global 32, local 16), 2000 passos, semente 0.
# Uso: FLOAT_LR=... TERN_LR=... ./run_scale.sh   (retoma de checkpoint se reiniciado)
cd "$(dirname "$0")"
STEPS=${STEPS:-2000}; SEED=${SEED:-0}
for GD in 64 96 128 192 256; do
  LD=$((GD/2)); GH=$((GD/32)); LH=$((LD/16))
  for V in float ternary; do
    OUT=results/scale/s${SEED}_${V}_g${GD}.json
    [ -f "$OUT" ] && continue
    FLAG=""; LR=$FLOAT_LR; [ "$V" = ternary ] && { FLAG="--ternary"; LR=$TERN_LR; }
    python3 train_patch2.py --steps $STEPS --gd $GD --ld $LD --gh $GH --lh $LH $FLAG --lr $LR --seed $SEED \
      --ckpt results/scale/s${SEED}_${V}_g${GD}.ck --out "$OUT" >> results/scale/s${SEED}_${V}_g${GD}.log 2>&1
  done
done
echo done > results/scale/S${SEED}_DONE
