#!/bin/bash
# largura 256 com lr=2e-3 (o 4e-3 deixou o float pior que a largura 192: sinal de taxa alta demais)
cd "$(dirname "$0")"
for V in float ternary; do
  OUT=results/lr256/${V}_g256_lr0.002.json; [ -f "$OUT" ] && continue
  FLAG=""; [ "$V" = ternary ] && FLAG="--ternary"
  python3 train_patch2.py --steps 2000 --gd 256 --ld 128 --gh 8 --lh 8 $FLAG --lr 0.002 --seed 0 --ckpt results/lr256/${V}.ck --out "$OUT" >> results/lr256/${V}.log 2>&1
done
echo done > results/lr256/DONE
