# Estudo de cobertura: quanto do trabalho real um agente sem modelo conseguiria produzir?

Pergunta falsificável: se o AURIX tivesse apenas uma camada determinística (formatação,
imports, remoções puras, renomear/ajustar literais, comentários), que fração das mudanças
reais de código dos repositórios do projeto ela cobriria?

Método: `classify.py REPO` percorre `git log -U0 --no-merges` e classifica cada hunk com
heurísticas conservadoras e auditáveis. Sem modelo, sem GPU, sem rede.
Resultados brutos em `results.jsonl` (6 repositórios, ~1100 commits).

## Resultado

| repo | hunks de código | hunks determinísticos | linhas determinísticas | commits de código 100% determinísticos |
|---|---:|---:|---:|---:|
| aegis | 106 | 21,7% | 0,3% | 0 / 22 |
| aurix | 1436 | 39,8% | 6,2% (*) | 41 / 261 |
| backend | 715 | 16,8% | 0,9% | 5 / 157 |
| saas-reputacao-ia | 374 | 11,5% | 0,3% | 3 / 27 |
| tax-platform-br | 704 | 18,0% | 3,0% | 17 / 277 |
| zion | 394 | 7,4% | 0,4% | 3 / 83 |

(*) 384 dos hunks do aurix são reformatação em massa; sem eles o número cai para perto dos outros.

## Interpretação (e limites)

- Pela contagem de linhas, uma camada sem modelo cobre de 0,3% a ~6% do que foi alterado.
  Esse é um **limite superior**: as categorias determinísticas só descrevem a *forma* da
  mudança. Saber *qual* import remover ou *qual* literal ajustar ainda exige intenção; uma auditoria
  manual de amostras confirmou que a classificação marca forma, não decisão.
- Logo, regras/codemods servem como **ferramenta** dentro do agente (e como verificadores),
  mas não substituem a parte generativa. A hipótese "o cérebro é um motor lógico sobre regras" não é
  sustentada por estes dados.
- Limitações: heurísticas simples; clones rasos (aegis, backend, saas-reputacao-ia, tax-platform-br)
  têm histórico truncado; "teste novo" foi contado como lógica nova; commits mistos não são separados.

## Consequência para a pesquisa

A parte generativa precisa ser aprendida. O trabalho de pesquisa passa a ser reduzir o custo *por
unidade de trabalho útil* da geração, medido com métricas fixas (bits por byte, FLOPs por byte e
taxa de resolução de tarefas verificadas), em vez de eliminá-la por decreto.
