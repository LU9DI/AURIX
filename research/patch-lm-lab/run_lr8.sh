#!/bin/bash
cd "$(dirname "$0")"
while [ ! -f results/lr/LR_EXTRA_DONE ]; do sleep 15; done
for V in ternary float; do
  OUT=results/lr/${V}_lr0.008.json; [ -f "$OUT" ] && continue
  FLAG=""; [ "$V" = ternary ] && FLAG="--ternary"
  python3 train_patch2.py --steps 1200 --gd 128 --ld 64 --gh 4 --lh 4 $FLAG --lr 0.008 --seed 0 --ckpt results/lr/${V}_lr0.008.ck --out "$OUT" >> results/lr/${V}_lr0.008.log 2>&1
done
echo done > results/lr/LR8_DONE
