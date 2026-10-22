#!/bin/bash
# lr=2e-3 no corpus atual (congelado), para comparar com a varredura
cd "$(dirname "$0")"
while [ ! -f results/lr/LR_DONE ]; do sleep 15; done
for V in ternary float; do
  OUT=results/lr/${V}_lr0.002.json; [ -f "$OUT" ] && continue
  FLAG=""; [ "$V" = ternary ] && FLAG="--ternary"
  python3 train_patch2.py --steps 1200 --gd 128 --ld 64 --gh 4 --lh 4 $FLAG --lr 0.002 --seed 0 --ckpt results/lr/${V}_lr0.002.ck --out "$OUT" >> results/lr/${V}_lr0.002.log 2>&1
done
echo done > results/lr/LR_EXTRA_DONE
