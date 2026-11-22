# Visão de pesquisa: Inteligência Estrutural Acumulativa

> **Tipo:** visão arquitetural e programa de pesquisa  
> **Status:** proposta; não representa capacidade implementada nem resultado experimental  
> **Projeto:** AURIX, com HPSI como linha complementar de inferência e AZTI como validação  
> **Princípio central:** não competir por contagem de parâmetros; investigar como acumular competência verificável com baixo custo operacional.

## 1. Resumo em linguagem simples

A proposta é construir um agente que fique mais competente ao longo do tempo porque aprende com experiências, organiza conhecimento, cria habilidades reutilizáveis, testa hipóteses e combina o que já sabe.

O sistema não deve depender de chamadas pagas a modelos remotos para cada decisão. Sua operação normal deve priorizar algoritmos locais, memória persistente, ferramentas determinísticas, execução em CPU e habilidades já verificadas. GPU e serviços de inferência pagos não são requisitos arquiteturais.

Isso **não significa custo zero**: CPU, RAM, armazenamento, rede, energia e manutenção continuam tendo custo. Também não significa que um agente sem modelo neural terá automaticamente a mesma capacidade de compreensão de um modelo de fronteira.

A hipótese a testar é que uma arquitetura híbrida, com memória e habilidades acumulativas, pode alcançar desempenho competitivo em domínios relevantes e superar agentes convencionais em algumas dimensões operacionais: custo recorrente, continuidade, rastreabilidade, repetibilidade e especialização acumulada.

## 2. O objetivo correto

Não construir apenas “um Claude Code menor”. Construir um agente que:

1. Receba objetivos e os decomponha em tarefas.
2. Pesquise fontes autorizadas e trate conteúdo externo como dado não confiável.
3. Construa conhecimento com origem, data, confiança e histórico.
4. Formule hipóteses e procure evidências favoráveis e contrárias.
5. Execute experimentos seguros para distinguir hipóteses.
6. Aprenda com sucessos e falhas, preservando contexto útil.
7. Transforme soluções comprovadas em habilidades versionadas e reutilizáveis.
8. Combine habilidades para resolver problemas novos.
9. Detecte quando não sabe, quando a evidência é insuficiente e quando precisa de ajuda.
10. Proponha melhorias em si mesmo, mas só promova mudanças após gates de validação.

A meta de comparação com Claude Code e outros agentes deve ser definida por tarefas, não por slogans. “Chegar perto” precisa significar uma taxa de sucesso mensurável em conjuntos de tarefas representativos.

## 3. Princípios não negociáveis

- **Sem dependência de tokens pagos:** nenhuma funcionalidade essencial pode exigir uma API paga para funcionar. Provedores externos podem existir apenas como adaptadores opcionais e explicitamente autorizados.
- **Sem dependência de GPU:** o caminho funcional principal deve executar em CPU. GPU pode ser aceleração opcional, nunca requisito.
- **Local-first e offline-capable:** tarefas já aprendidas devem continuar executáveis sem internet. Pesquisa na web depende de conectividade e autorização.
- **Evidência antes de confiança:** toda memória importante deve indicar fonte, data, método de obtenção e nível de confiança.
- **Determinismo onde possível:** parsing, validação, políticas, execução de ferramentas, testes e operações repetíveis devem preferir código determinístico.
- **Probabilidade onde necessário:** inferência neural pode ajudar com ambiguidade, mas seus resultados precisam ser verificados.
- **Aprendizagem sem autoengano:** uma execução bem-sucedida não prova competência geral; resultados devem ser reproduzidos em casos novos.
- **Segurança por padrão:** isolamento, limites de CPU/RAM/tempo, allowlists, permissões mínimas, logs e recuperação conservadora.
- **Promoção controlada:** o agente não pode alterar o próprio núcleo operacional nem conceder autoridade a uma habilidade sem testes, revisão e política explícita.
- **Medição comparável:** toda alegação de melhoria deve ter baseline, tarefas, ambiente, repetições, métricas e artefatos reproduzíveis.

## 4. Arquitetura conceitual

### 4.1 AURIX — orquestração e autonomia operacional

Responsável por planejar, decompor objetivos, escolher ferramentas, agendar tarefas, impor limites, controlar workers, manter trilhas de auditoria e coordenar os demais motores.

O AURIX é o sistema que decide **o que fazer, em que ordem, com quais permissões e sob quais limites**. O núcleo de segurança não deve depender de um modelo probabilístico.

### 4.2 Memory Engine — memória persistente e verificável

Manter tipos de memória separados, com políticas distintas:

- **Memória episódica:** o que aconteceu em uma execução, decisões, ferramentas usadas, resultados e erros.
- **Memória semântica:** fatos, conceitos e relações com fontes e validade temporal.
- **Memória procedural:** habilidades, instruções executáveis, pré-condições e limites conhecidos.
- **Memória de trabalho:** contexto temporário da tarefa atual, com orçamento explícito.
- **Memória de hipóteses:** conjecturas ainda não confirmadas, evidências contrárias e experimentos pendentes.

Cada registro relevante deve conter identificador, origem, timestamp, escopo, confiança, versão, hash quando aplicável e estado (proposto, verificado, contestado, expirado ou rejeitado). Não misturar hipótese com fato confirmado.

### 4.3 Research & Curiosity Engine — pesquisa e curiosidade

O motor identifica lacunas, contradições, dependências desconhecidas e perguntas de alto valor. Ele propõe objetivos de pesquisa e prioriza por utilidade esperada, custo, risco e incerteza.

A curiosidade não deve ser uma fila ilimitada de buscas. Deve obedecer a orçamento de CPU, RAM, rede, disco, tempo e políticas de domínio. Deve evitar ciclos de pesquisa sem ganho informacional.

### 4.4 Hypothesis & Causal Engine — hipóteses e causalidade

O agente deve distinguir:
- correlação observada;
- explicação plausível;
- hipótese causal;
- evidência experimental;
- conclusão limitada ao contexto testado.

Fluxo sugerido:
1. formular hipótese falsificável;
2. declarar previsões e condições;
3. buscar evidências favoráveis e contrárias;
4. identificar confundidores e explicações alternativas;
5. desenhar teste ou simulação segura;
6. registrar resultado bruto e método;
7. atualizar confiança sem apagar histórico.

Modelos causais e simulações são linhas de pesquisa, não capacidades presumidas.

### 4.5 Skill Engine — cristalização e composição de habilidades

Uma solução só pode virar habilidade reutilizável depois de:
- identificar o problema e o domínio de validade;
- extrair pré-condições, entradas, saídas e efeitos colaterais;
- converter a solução em programa, regra, parser ou workflow;
- criar testes positivos, negativos e adversariais;
- executar em ambiente isolado ou fixture descartável;
- medir recursos e comportamento;
- registrar versão, proveniência, dependências e rollback.

Habilidades devem ter níveis de confiança e autoridade. Uma habilidade experimental não pode executar ações privilegiadas. A composição de habilidades deve verificar compatibilidade de tipos, pré-condições, permissões e invariantes.

“Compile once, run many” é uma meta de amortização, não uma garantia de que toda solução possa ser convertida em código determinístico.

### 4.6 Reasoning Engine — raciocínio e resolução

Combinar métodos adequados ao problema:
- regras e máquinas de estado;
- busca em grafos e planejamento;
- SAT/SMT e solucionadores de restrições;
- síntese de programas e transformação de AST;
- e-graphs para equivalências quando apropriado;
- estatística e modelos probabilísticos para incerteza;
- modelos neurais locais como auxiliares, não como autoridade de segurança.

Nenhum método deve ser escolhido por moda. Cada um precisa demonstrar utilidade em tarefas reais.

### 4.7 HPSI — inferência compacta experimental

HPSI pode se tornar uma camada de inferência local em CPU, desde que a prova de conceito demonstre simultaneamente:
- ausência de reconstrução integral de tensores no caminho de inferência definido;
- footprint de memória medido, incluindo page cache e buffers relevantes;
- latência mediana e cauda;
- throughput;
- tráfego de disco e page faults;
- erro numérico e qualidade da tarefa;
- comparação com baselines INT8/INT4 e outras representações;
- estabilidade e portabilidade entre CPUs.

HPSI não deve ser descrito como “cérebro do AURIX” nem como solução semântica até que a qualidade de saída seja comparável em tarefas representativas. A integração inicial deve ser worker isolado, shadow-only, sem autoridade funcional.

### 4.8 AZTI — validação e confiança

AZTI deve validar:
- equivalência funcional;
- regressões;
- contenção de CPU/RAM/tempo;
- ausência de processos órfãos;
- integridade de artefatos;
- repetibilidade;
- independência de auditoria;
- comportamento sob falhas e entradas adversariais.

O mesmo rigor deve ser aplicado a habilidades aprendidas e componentes HPSI. Resultados devem separar PASS, FAIL, INCONCLUSIVE e NOT_TESTED. Ausência de evidência nunca é PASS.

## 5. Ciclo de aprendizagem acumulativa

1. **Observar:** receber objetivo, contexto e dados autorizados.
2. **Planejar:** decompor em subtarefas e declarar critérios de sucesso.
3. **Investigar:** consultar memória, ferramentas e fontes.
4. **Hipotetizar:** formular explicações e alternativas.
5. **Experimentar:** executar testes controlados e reversíveis.
6. **Avaliar:** comparar resultados com previsões e baseline.
7. **Consolidar:** guardar fatos, episódios, hipóteses e erros separadamente.
8. **Cristalizar:** propor habilidade reutilizável quando houver evidência suficiente.
9. **Compor:** combinar habilidades aprovadas para novos objetivos.
10. **Reavaliar:** detectar obsolescência, contradições e regressões.

O ciclo deve poder parar por falta de evidência, orçamento, permissão ou segurança. Não deve improvisar uma conclusão para satisfazer o objetivo.

## 6. Operação econômica: sem tokens pagos e sem GPU como requisito

A arquitetura deve privilegiar:
- execução de habilidades locais já verificadas;
- parsers e processamento em streaming;
- índices compactos e acesso seletivo;
- deduplicação e cache com invalidação explícita;
- armazenamento append-only para eventos e consolidação em períodos ociosos;
- workers com limites rígidos e reciclagem controlada;
- CPU e memória mapeada quando a medição justificar;
- modelos locais pequenos apenas quando agregarem valor demonstrável;
- HPSI como experimento para inferência compacta em CPU.

Não assumir que mmap elimina RAM, que XOR/POPCNT substitui compreensão semântica, que armazenar trilhões de fatos equivale a trilhões de parâmetros, ou que o custo computacional é zero. Medir RSS, working set, page faults, cache do SO, I/O, CPU, energia quando possível e latência de cauda.

O orçamento operacional deve ser configurável por máquina. A guarda de RAM usada nos experimentos AZTI é uma restrição de laboratório, não um limite universal nem uma garantia de que qualquer modelo caiba nela.

## 7. Como avaliar proximidade com Claude Code e outros agentes

Não comparar por impressão subjetiva, número de parâmetros, velocidade isolada ou quantidade de ferramentas. Construir um benchmark próprio, público e reproduzível, com tarefas representativas:

- localizar e corrigir bugs;
- implementar pequenas funcionalidades;
- compreender repositórios desconhecidos;
- depurar falhas de testes;
- modificar múltiplos arquivos com coerência;
- refatorar preservando comportamento;
- explicar decisões com referências ao código;
- recuperar-se de ferramentas que falham;
- continuar tarefas após reinício;
- aprender uma habilidade e reutilizá-la em um caso novo;
- compor duas ou mais habilidades para uma tarefa inédita;
- reconhecer quando não há evidência suficiente.

Para cada tarefa, medir:
- sucesso funcional por testes independentes;
- taxa de regressão;
- qualidade da solução por revisão cega;
- número de intervenções humanas;
- tempo total e latência de cauda;
- CPU, RAM de pico, I/O e energia quando disponível;
- custo monetário de inferência (meta operacional: zero tokens pagos);
- robustez a perturbações e entradas adversariais;
- retenção e transferência de habilidades para tarefas novas.

Comparação justa exige mesmo conjunto de tarefas, mesmo estado inicial, critérios de sucesso equivalentes, múltiplas tentativas e registro das versões dos sistemas. Não alegar paridade geral com Claude Code a partir de um subconjunto favorável.

## 8. Roteiro de pesquisa proposto

### Fase 0 — Formalizar e proteger a visão
- manter este documento como visão de pesquisa, não especificação de implementação;
- definir vocabulário, fronteiras entre AURIX/HPSI/AZTI e princípios de segurança;
- registrar hipóteses e critérios de refutação.

### Fase 1 — Memória verificável
- esquema de memória episódica, semântica, procedural e de hipóteses;
- proveniência, validade temporal, versionamento e conflitos;
- testes de corrupção, duplicação, expiração e recuperação;
- avaliação de recuperação correta e prevenção de falsas lembranças.

### Fase 2 — Curiosidade e pesquisa controlada
- gerador de perguntas e priorização por valor informacional;
- limites de recursos e rede;
- proteção contra prompt injection e fontes maliciosas;
- avaliação de novidade, precisão e custo.

### Fase 3 — Habilidades reutilizáveis
- formato versionado de habilidade;
- pré-condições, permissões, dependências e efeitos;
- sandbox/fixtures e testes adversariais;
- promoção por evidência e rollback;
- benchmark de reutilização em tarefas não idênticas.

### Fase 4 — Planejamento, composição e causalidade
- planejamento com estados explícitos;
- composição tipada de habilidades;
- hipóteses falsificáveis e experimentos;
- avaliação de transferência para problemas inéditos.

### Fase 5 — HPSI como worker shadow
- concluir PoC independente;
- comparar com baselines;
- provar qualidade e footprint real;
- integrar apenas por interface isolada e sem autoridade.

### Fase 6 — Benchmark externo e evolução
- comparar AURIX com agentes de referência em tarefas comuns;
- auditoria independente dos resultados;
- autoaperfeiçoamento apenas em branch/worktree descartável;
- promoção somente após todos os gates.

A ordem pode mudar conforme evidências; nenhuma fase é considerada concluída apenas por documentação ou arquitetura desenhada.

## 9. Riscos e hipóteses que precisam ser refutadas

| Hipótese | Risco | Como testar |
|---|---|---|
| Habilidades acumuladas reduzem chamadas de inferência | Soluções não generalizam ou ficam obsoletas | medir reutilização em tarefas novas e regressões |
| Conhecimento explícito melhora rastreabilidade | Base cresce, mas recuperação fica lenta ou contraditória | medir precisão, recall, latência e resolução de conflitos |
| Composição gera competência emergente | Erros se multiplicam entre habilidades | tarefas inéditas, contratos e testes adversariais |
| Inferência HPSI cabe em CPU | page faults e I/O dominam a latência | medir memória física, page faults, I/O e cauda |
| Curiosidade melhora conhecimento | agente entra em loops ou coleta ruído | medir ganho informacional por custo |
| Núcleo determinístico reduz falhas | regras rígidas não cobrem casos novos | medir cobertura, abstenção e taxa de erro |
| O sistema pode se autoaperfeiçoar | otimiza métricas locais e degrada comportamento | benchmark holdout, revisão independente e rollback |

## 10. O que não devemos afirmar

Até haver provas, não afirmar:
- que AURIX é AGI ou está próximo de AGI;
- que 90% das tarefas podem ser resolvidas sem inferência neural;
- que HPSI já executa modelos úteis dentro de uma guarda de RAM específica;
- que bilhões/trilhões de fatos equivalem a parâmetros de um modelo;
- que código determinístico é infalível;
- que o agente supera Claude Code ou qualquer agente de fronteira;
- que operação sem GPU ou tokens pagos significa custo zero;
- que uma habilidade aprendida funciona fora do seu domínio testado.

## 11. Definição de sucesso

O sucesso inicial não é “ser AGI”. É demonstrar, em uma classe crescente de tarefas, que o sistema:
1. resolve tarefas com qualidade mensurável;
2. aprende uma habilidade verificável;
3. reutiliza essa habilidade em um problema diferente;
4. combina habilidades para resolver uma tarefa mais complexa;
5. identifica limites e sabe abster-se;
6. mantém desempenho e segurança após muitas sessões;
7. opera sem tokens pagos e sem GPU;
8. melhora em benchmarks holdout sem degradar resultados anteriores.

## 12. Decisão arquitetural recomendada

Manter AURIX, HPSI e AZTI como projetos com responsabilidades distintas e interfaces explícitas:

- **AURIX:** autonomia, planejamento, ferramentas, memória, habilidades, políticas e execução.
- **HPSI:** pesquisa de inferência compacta local; experimental até prova de qualidade e eficiência.
- **AZTI:** testes, auditoria, contenção, integridade e evidência para qualquer promoção.

A prioridade é construir primeiro memória verificável, aprendizagem por experiência, habilidades reutilizáveis e avaliação. Não integrar módulos experimentais ao núcleo crítico antes de demonstrar valor.

---

**Tese central:** buscar uma inteligência operacional que cresça por conhecimento verificável, experimentação, composição e habilidades acumuladas — com CPU como plataforma suficiente para o caminho principal, sem tokens pagos como dependência e sem GPU como requisito. A proximidade com agentes de fronteira deve ser conquistada tarefa por tarefa, com benchmarks reproduzíveis, não presumida pela arquitetura.
