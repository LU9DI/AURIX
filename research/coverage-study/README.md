# Estudo de cobertura: quanto do trabalho real um agente sem modelo conseguiria produzir?

Pergunta falsificável: se o AURIX tivesse apenas uma camada determinística (formatação,
imports, remoções puras, renomear/ajustar literais, comentários), que fração das mudanças
reais de código dos repositórios do projeto ela cobriria?

## Método

`classify.py REPO` percorre `git log --no-merges -p -U0` e classifica cada hunk com
heurísticas conservadoras e auditáveis. O `-p` é essencial: sem ele, o Git não emite os
patches e o estudo pode contar zero alterações sem falhar. Falhas do Git agora provocam erro
explícito, em vez de serem tratadas como histórico vazio.

## Resultados

Regenerados com o extrator corrigido (`results.jsonl`, com commit, profundidade e hash do classificador
de cada snapshot; todos na branch principal de cada repositório, quatro deles em clones rasos).
"Sem commits em massa" exclui commits com mais de 1500 linhas de código alteradas (`sensitivity.py`).

| repo | commits | hunks de código | hunks determinísticos | linhas determinísticas | linhas det. sem commits em massa | commits de código 100% det. |
|---|---:|---:|---:|---:|---:|---:|
| aegis | 88 | 76 | 3,9% | 0,0% | 0,3% | 0 / 21 |
| aurix | 320 | 1528 | 43,4% | 31,1% (*) | 5,9% | 42 / 262 |
| backend | 192 | 710 | 16,8% | 0,9% | 4,4% | 5 / 156 |
| saas-reputacao-ia | 50 | 375 | 11,7% | 0,4% | 8,1% | 4 / 28 |
| tax-platform-br | 267 | 628 | 17,8% | 2,9% | 3,8% | 15 / 259 |
| zion | 164 | 393 | 7,1% | 0,4% | 2,0% | 2 / 82 |

(*) 13.420 das linhas do aurix são remoções de arquivos inteiros, que o extrator anterior ignorava.
É uma operação mecânica, mas não é geração de código; sem esses commits em massa o valor cai para 5,9%.

Leitura: em commits normais, uma camada sem modelo cobre de 0,3% a ~8% das linhas alteradas. É um
limite superior: as categorias só descrevem a *forma* da mudança, não a decisão de qual mudança fazer.

## Limitações da classificação

- As categorias são heurísticas sobre a forma do diff, não sobre a intenção. Uma mudança
  classificada como determinística ainda pode exigir entendimento para decidir *o que* alterar.
- `teste_novo` é separado da lógica comum, mas continua sendo trabalho que exige especificação.
- Commits mistos não são separados em unidades de intenção; arquivos gerados, formatação em massa
  e alterações de configuração podem distorcer contagens.
- Uma fração de linhas ou hunks não equivale diretamente à fração de trabalho ou esforço poupável.

## Experimentos seguintes: o que o projeto consegue reaproveitar de si mesmo?

Todos usam só informação **anterior** ao que está sendo previsto, sobre os mesmos snapshots. Scripts
e saídas brutas estão nesta pasta (`reuse.py`, `copy_cov.py`, `chrono_bits.py`, `prior_corpus.py`, `sensitivity.py`,
`results_*.txt`, `copy_results.jsonl`).

### Reuso de identificadores e moldes (`copy_cov.py`)

Para os hunks de "lógica nova", usando só o histórico anterior a cada commit:

| repo | identificadores já conhecidos | hunks com 100% dos identificadores conhecidos | linhas com molde já visto |
|---|---:|---:|---:|
| aegis | 69,6% | 4,3% | 21,2% |
| aurix | 66,0% | 68,8% | 51,8% |
| backend | 87,7% | 47,5% | 9,8% |
| saas-reputacao-ia | 85,1% | 48,3% | 2,4% |
| tax-platform-br | 88,4% | 46,1% | 27,1% |
| zion | 32,3% | 14,8% | 7,3% |

(Esta tabela inclui commits em massa; a próxima os exclui.)

### Linha nova = molde + campos? (`reuse.py`)

Linhas não triviais de "lógica nova" em commits de até 1500 linhas, contando só commits anteriores.
"molde" = alguma linha anterior com a mesma forma (identificadores e literais abstraídos).
"molde+campos" = um dos 3 moldes mais recentes, com cada campo igual ao do molde ou entre os k=5
tokens mais recentes do mesmo arquivo. "teto" aceita qualquer token já visto no repositório
(um ranker perfeito).

| repo | linhas | exata | molde | molde+campos (k=5) | teto (qualquer token do repo) |
|---|---:|---:|---:|---:|---:|
| aurix | 1190 | 28,5% | 70,6% | 18,7% | 46,9% |
| backend | 3386 | 35,4% | 67,3% | 24,3% | 46,9% |
| tax-platform-br | 2845 | 19,9% | 59,7% | 16,7% | 34,7% |
| zion | 1738 | 16,3% | 49,9% | 12,3% | 30,7% |
| aegis | 1584 | 10,2% | 44,2% | 7,5% | 13,5% |
| saas-reputacao-ia | 1000 | 11,7% | 60,5% | 4,9% | 27,4% |

**Correção.** Uma medição anterior contava linhas copiadas *dentro do mesmo commit* e commits em massa
(importação inicial de clones rasos), o que dava 50–83% de reuso. `reuse.py --within-commit` reproduz
esse tipo de número inflado (ver `results_reuse.txt`). O valor causal é o da tabela acima.

Leitura: a *forma* de uma linha nova costuma existir (44–71%), mas reproduzir a linha inteira escolhendo
os campos com um ranker simples por recência cobre só 5–24%, e mesmo um ranker perfeito, com o
vocabulário do repositório inteiro, tem teto de 13–47%. Boa parte do código novo traz identificadores,
literais ou combinações que o projeto ainda não tinha.

### Onde está a informação: estrutura ou conteúdo? (`chrono_bits.py`)

Um n-gram de bytes (ordem 10, depende do PR #7), treinado só no passado cronológico, mede os bits por
byte do código novo (commits normais). Cada byte é atribuído a conteúdo (identificadores, strings,
números) ou estrutura (palavras-chave, pontuação, espaços):

| repo | BPB médio | bits em estrutura |
|---|---:|---:|
| tax-platform-br | 2,50 | 18,6% |
| aurix | 2,55 | 15,5% |
| backend | 3,13 | 11,1% |
| zion | 3,33 | 15,5% |
| aegis | 2,98 | 18,8% |
| saas-reputacao-ia | 3,74 | 18,9% |

Se uma linguagem de operações tornasse a estrutura *gratuita*, a economia máxima de informação seria de
~11–19% dos bits. A informação difícil está no conteúdo, que qualquer representação precisa carregar.

Limitações: os fluxos têm só 100–350 KB; o BPB por bloco é muito irregular (não dá para afirmar que o
erro cai com mais passado); é n-gram, não rede neural; a separação estrutura/conteúdo é por regex, sem
árvore sintática; clones rasos.

### Mais conhecimento prévio ajuda? (`prior_corpus.py`)

Mesmo teste cronológico (último bloco do código novo), comparando: A = só o passado do repositório,
B = só um corpus genérico de terceiros, C = genérico + passado (`results_prior.txt`).

| caso | A | B | C |
|---|---:|---:|---:|
| aurix (Python), genérico 1,5 MB | 3,61 | 4,16 | 3,10 |
| aurix (Python), genérico 4 MB | 3,61 | 3,92 | 3,03 |
| aurix (Python), genérico 12 MB | 3,61 | 3,80 | 3,03 |
| tax-platform-br (TS), genérico 12 MB | 2,56 | 6,15 | 2,76 |

Em Python, juntar um corpus genérico baixa ~16% e satura em 3,03 já com 4 MB; sozinho, o corpus genérico
melhora devagar (4,16 → 3,80 em 8x mais dados). Em TypeScript o resultado é inconclusivo: o único corpus
local disponível é JavaScript compilado de `node_modules`, de estilo diferente, e piorou o resultado.
Um n-gram não generaliza entre nomes parecidos; mais dados dele têm retorno decrescente.

## Consequências

1. Regras determinísticas (0,3–8% das linhas em commits normais) e copiar-e-editar com ranker simples
   (5–24% das linhas) não bastam como núcleo gerativo.
2. Trocar o texto por uma representação estrutural ajuda pouco no limite de informação: ≤ ~11–19% dos bits.
3. O que sobra é modelar o conteúdo (nomes, literais, intenção), o que um modelo treinado faz. O caminho
   de pesquisa é tornar esse modelo barato (menos computação por byte), medido contra estas linhas de base.

## Execução reproduzível

Com os repositórios já clonados localmente, execute o runner passando o arquivo de saída e
os diretórios dos snapshots:

```bash
python research/coverage-study/run_study.py research/coverage-study/results.jsonl /caminho/para/AURIX /caminho/para/AEGIS
```

O runner não clona nem atualiza repositórios: isso evita alterar silenciosamente os snapshots
medidos. Cada linha JSONL inclui o commit exato, URL de `origin` (quando configurada), se o
clone é raso, quantidade de commits disponíveis no histórico e SHA-256 do classificador.
O caminho absoluto local não é publicado: só o nome do snapshot é registrado. Em origens HTTP(S),
credenciais, query strings e fragmentos são removidos antes de gravar a URL.
Passe todos os snapshots pretendidos numa única execução para substituir o arquivo de resultados
de uma vez; se algum snapshot falhar, o arquivo de saída anterior não é truncado.

Repositórios privados precisam estar clonados com credenciais próprias antes da execução. Não
inclua tokens ou credenciais nas URLs de origem gravadas nos resultados; prefira URLs sem segredo.
