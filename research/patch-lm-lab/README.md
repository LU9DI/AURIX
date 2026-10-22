# Laboratório: modelo de patches de bytes, float vs. ternário

Pergunta: um modelo **sem vocabulário** (patches dinâmicos de bytes, estilo Byte Latent Transformer) com
**pesos ternários** (estilo BitNet b1.58, em que o produto por peso vira soma/subtração) perde muito em
qualidade em relação à versão em ponto flutuante, e essa perda diminui com o tamanho?

## Método
- `train_patch.py`: segmentação em patches pela entropia de um n-grama de bytes; transformer global só sobre
  os patches e decoder local por byte; métrica em bits por byte (BPB) na validação por arquivo
  (`corpus.py`: código .py/.js/.ts dos repositórios do projeto, sem duplicatas exatas ou quase exatas).
- `--ternary`: as camadas lineares dos blocos usam pesos em {-1, 0, +1} × escala (absmean) e ativações int8
  por token, com estimador straight-through. É **simulado em ponto flutuante**: mede qualidade, não acelera
  nada nesta CPU (os tempos ternários foram até maiores).
- Mesmo número de passos (1200, 16 sequências de 512 bytes por passo), 3 larguras, semente 0;
  sementes 0 e 1 nas duas menores (`run_ternary.sh`, `run_ternary_seed1.sh`).

## Resultados (BPB na validação; menor é melhor)

| largura (global/local) | parâmetros | float | ternário | diferença |
|---|---:|---:|---:|---:|
| 64 / 32 | 263 mil | 3,023 / 3,006 | 3,300 / 3,292 | +9,2% / +9,5% |
| 128 / 64 | 977 mil | 2,588 / 2,562 | 2,891 / 2,851 | +11,7% / +11,3% |
| 256 / 128 | 3,76 mi | 2,294 | 2,443 | +6,5% |

(duas sementes onde há duas; a diferença entre sementes é ~0,01–0,04 BPB.)

Multiplicações-acumulações lineares por byte nos blocos: 73 mil, 292 mil e 1,17 mi (larguras 64, 128, 256).
No ternário elas viram somas; as demais partes (embeddings, cabeça de saída, atenção) continuam em ponto flutuante.

## Leitura
- A perda do ternário em relação ao float ficou entre 6,5% e 11,7%. Não foi monotônica: subiu de 64 para 128
  (acima do ruído entre sementes) e caiu em 256. Com três larguras, uma só semente na maior e modelos
  subtreinados (BPB 2,3–3,0, longe dos 1,71 de uma execução de 25 min), **não dá para afirmar que a
  diferença encolhe com o tamanho**. O resultado é compatível com isso, não o demonstra.
- Os números absolutos deste porte não valem; só a tendência valeria, e ela precisa de mais larguras,
  mais sementes e treino mais longo.
- Não medi energia nem velocidade: exigiriam kernels dedicados.
- `corpus.py` lê os repositórios locais como estão no momento da execução; os resultados correspondem ao
  corpus daquela data.
