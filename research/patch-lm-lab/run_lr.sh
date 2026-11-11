#!/bin/bash
# Varredura de taxa de aprendizado, largura 128, 1200 passos, semente 0 (lr=2e-3 ja existe em results/tern)
cd "$(dirname "$0")"
for V in ternary float; do
  for LR in 0.004 0.001; do
    OUT=results/lr/${V}_lr${LR}.json
    [ -f "$OUT" ] && continue
    FLAG=""; [ "$V" = ternary ] && FLAG="--ternary"
    python3 train_patch2.py --steps 1200 --gd 128 --ld 64 --gh 4 --lh 4 $FLAG --lr $LR --seed 0 \
      --ckpt results/lr/${V}_lr${LR}.ck --out "$OUT" >> results/lr/${V}_lr${LR}.log 2>&1
  done
done
echo done > results/lr/LR_DONE
