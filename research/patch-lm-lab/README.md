# Laboratório: modelo de patches de bytes, float vs. ternário

Pergunta: um modelo **sem vocabulário** (patches dinâmicos de bytes, estilo Byte Latent Transformer) com
**pesos ternários** (estilo BitNet b1.58, em que o produto por peso vira soma/subtração) perde pouco em
qualidade em relação à versão em ponto flutuante, e essa perda diminui com o tamanho?

## Método
- `train_patch.py`: segmentação em patches pela entropia de um n-grama de bytes; transformer global só sobre
  os patches e decoder local por byte; métrica em bits por byte (BPB) na validação por arquivo.
- `--ternary`: as camadas lineares dos blocos usam pesos em {-1, 0, +1} × escala (absmean) e ativações int8
  por token, com estimador straight-through. É **simulado em ponto flutuante**: mede qualidade, não acelera
  nada (os tempos ternários foram até maiores). Mesmo número de passos nas duas variantes.
- Corpus: código .py/.js/.ts dos repositórios do projeto (`corpus.py`), sem duplicatas exatas ou quase
  exatas, validação por arquivo. Os resultados de `results/` usam um corpus **congelado**
  (`freeze_corpus.py`; 465 arquivos, 3,66 MB, hash 76c4231dcbce24f5); o snapshot não é versionado por conter
  código privado. A pasta `initial/` usou o corpus vivo de uma data anterior; **não é comparável**.
- Uma semente (0) em `results/`.

## Correção de um resultado anterior
O primeiro teste (`initial/`) usava a mesma taxa de aprendizado (2e-3) para as duas variantes e mostrava
perdas de +6,5% a +11,7%. A varredura de taxa abaixo mostra que isso **superestimava** o problema, e que a
taxa ótima muda com a largura.

## 1. Varredura de taxa de aprendizado (largura 128, 1200 passos)

| taxa | float | ternário |
|---|---:|---:|
| 1e-3 | 2,910 | 3,147 |
| 2e-3 | 2,648 | 2,921 |
| 4e-3 | **2,538** | **2,670** |
| 8e-3 | 2,556 | 2,676 |

Com a taxa ótima (4e-3 nos dois) a perda do ternário é **+5,2%**; a 2e-3 seria +10,3%.

## 2. Curva de escala (2000 passos, taxa 4e-3 nos dois, cabeças de dimensão fixa)

| largura | parâmetros | float | ternário | perda do ternário |
|---|---:|---:|---:|---:|
| 64 | 263 mil | 2,625 | 2,907 | +10,8% |
| 96 | 564 mil | 2,355 | 2,634 | +11,8% |
| 128 | 977 mil | 2,307 | 2,455 | +6,4% |
| 192 | 2,14 mi | 2,132 | 2,243 | +5,2% |
| 256 | 3,76 mi | 2,151 | 2,172 | +1,0% |

O float em 256 ficou pior que em 192 com os mesmos passos: sinal de taxa alta demais para essa largura.
Refeito com taxa 2e-3 (`results/lr256/`): float **2,020** e ternário **2,171**, perda **+7,5%**.
O "+1,0%" era um artefato da taxa.

## Leitura
- Com a taxa corrigida, a perda do ternário fica entre ~5% e ~12% em toda a faixa (263 mil a 3,76 mi de
  parâmetros), **sem tendência clara de queda**. Só as larguras 128 e 256 tiveram a taxa ajustada; 64, 96 e 192
  provavelmente também estão fora do ótimo, o que torna as perdas desses pontos incertas.
- Neste porte e com este orçamento, o resultado não sustenta que a diferença desapareça com o tamanho. A
  literatura reporta paridade só em escalas bem maiores (bilhões de parâmetros), que este ambiente (2 CPUs)
  não alcança.
- Não medi energia nem velocidade: exigiriam kernels dedicados.
- Fica uma lição de método: toda comparação entre arquiteturas precisa de taxa de aprendizado ajustada por
  variante **e por largura**, e de corpus congelado.
