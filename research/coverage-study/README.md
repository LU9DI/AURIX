# Estudo de cobertura: quanto do trabalho real um agente sem modelo conseguiria produzir?

Pergunta falsificável: se o AURIX tivesse apenas uma camada determinística (formatação,
imports, remoções puras, renomear/ajustar literais, comentários), que fração das mudanças
reais de código dos repositórios do projeto ela cobriria?

## Método

`classify.py REPO` percorre `git log --no-merges -p -U0` e classifica cada hunk com
heurísticas conservadoras e auditáveis. O `-p` é essencial: sem ele, o Git não emite os
patches e o estudo pode contar zero alterações sem falhar. Falhas do Git agora provocam erro
explícito, em vez de serem tratadas como histórico vazio.

## Estado dos resultados

**Os números em `results.jsonl` são históricos e não devem ser usados como evidência ainda.**
A extração de patches foi corrigida, mas os resultados precisam ser regenerados com o extrator
corrigido e com os mesmos snapshots de repositório documentados. Até isso acontecer, removemos
a tabela e as conclusões quantitativas para não apresentar medições possivelmente inválidas
como se estivessem verificadas.

A execução reproduzível deverá registrar, para cada repositório, o commit analisado, a origem
do clone, a profundidade do histórico e a saída completa do classificador. Clones rasos limitam
a inferência ao histórico disponível; não representam necessariamente toda a atividade do projeto.

## Limitações da classificação

- As categorias são heurísticas sobre a forma do diff, não sobre a intenção. Uma mudança
  classificada como determinística ainda pode exigir entendimento para decidir *o que* alterar.
- `teste_novo` é separado da lógica comum, mas continua sendo trabalho que exige especificação.
- Commits mistos não são separados em unidades de intenção; arquivos gerados, formatação em massa
  e alterações de configuração podem distorcer contagens.
- Uma fração de linhas ou hunks não equivale diretamente à fração de trabalho ou esforço poupável.

## Próxima etapa

Regenerar `results.jsonl` a partir de snapshots identificados e auditar manualmente amostras
das categorias. Só então publicar percentuais, incluindo uma análise de sensibilidade que exclua
reformatação em massa e compare resultados por repositório.
