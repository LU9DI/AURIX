# AURIX-IGE-01 — Protocolo experimental de aprendizagem, transferência e composição

> **Tipo:** protocolo de pesquisa e avaliação  
> **Projeto:** AURIX  
> **Linha:** Inteligência Generativa Estrutural (IGE)  
> **Status:** proposto; ainda não executado  
> **Natureza:** experimento CPU-first, sem dependência de GPU ou tokens pagos  
> **Regra:** este documento define como testar uma hipótese; não declara capacidades implementadas.

## 1. Pergunta científica

Um agente pode adquirir uma habilidade verificável a partir de experiências, reutilizá-la em problemas diferentes e combinar essa habilidade com outra para resolver tarefas novas, mantendo qualidade e segurança, sem depender de inferência remota paga ou GPU?

O experimento deve separar três alegações:

- **H1 — Aquisição:** o sistema consegue transformar uma solução validada em uma habilidade executável, documentada e testável.
- **H2 — Transferência:** a habilidade melhora o desempenho em instâncias inéditas, não usadas para construí-la.
- **H3 — Composição:** duas habilidades individualmente verificadas podem ser compostas para resolver uma tarefa que nenhuma delas resolve sozinha.

H1, H2 e H3 são hipóteses. Nenhuma é considerada verdadeira antes da execução e avaliação independente.

## 2. Escopo e não objetivos

### Dentro do escopo

- Aprendizagem a partir de experiências de tarefas determinísticas.
- Extração de pré-condições, entradas, saídas, invariantes e limites.
- Geração de uma habilidade executável em formato versionado.
- Testes de regressão, casos negativos e holdout.
- Recuperação da habilidade após encerramento e reinício do processo.
- Transferência para instâncias novas e composição de habilidades.
- Medição de qualidade, intervenções, CPU, memória, tempo e I/O.

### Fora do escopo

- Alegar AGI, inteligência geral ou paridade com Claude Code.
- Treinar pesos de um modelo neural.
- Exigir GPU, APIs pagas ou tokens externos.
- Permitir autoalteração irrestrita do núcleo do AURIX.
- Dar autoridade privilegiada a habilidades recém-geradas.
- Usar os resultados de treino como prova de generalização.
- Integrar HPSI ao caminho crítico.
- Promover automaticamente uma habilidade à produção.

## 3. Princípios experimentais

1. **Pré-registro:** tarefas, divisões, métricas, limites e critérios devem ser congelados antes da avaliação holdout.
2. **Separação treino/teste:** nenhuma instância holdout, semente, resposta esperada ou fixture privada pode ser usada na construção da habilidade.
3. **Avaliação independente:** resultados são verificados por testes/oráculos separados do gerador da habilidade.
4. **Reprodutibilidade:** registrar versões, hashes, configuração, ambiente, sementes, logs e resultados brutos.
5. **Abstenção:** se não houver evidência suficiente ou os limites forem excedidos, o agente deve parar e reportar.
6. **Sem contaminação:** não usar conteúdo de holdout em prompts, memória, exemplos, depuração ou ajuste manual.
7. **Comparação justa:** todos os braços recebem o mesmo orçamento de tarefas e recursos.
8. **Sem promoção por conveniência:** falha ou resultado inconclusivo não pode ser convertido em PASS alterando critérios após observar resultados.

## 4. Desenho experimental

### 4.1 Braços de comparação

| Braço | Configuração | Pergunta |
|---|---|---|
| A — Baseline frio | Sem memória persistente específica e sem habilidade aprendida | Qual é o desempenho sem aprendizagem acumulada? |
| B — Memória | Memória de experiências e fatos, sem habilidade procedural executável | A memória, isoladamente, ajuda? |
| C — Habilidade | Habilidade cristalizada e validada, recuperada após reinício | A habilidade transfere competência? |
| D — Composição | Duas ou mais habilidades validadas, ligadas por contratos explícitos | A composição acrescenta capacidade? |

O braço B não pode armazenar a solução holdout. O braço C não pode receber a resposta esperada das tarefas de teste. O braço D só pode compor habilidades aprovadas antes da avaliação.

### 4.2 Fases

- **F0 — Pré-registro:** publicar protocolo, fixtures de treino, geradores, métricas e critérios.
- **F1 — Baseline:** executar A nas tarefas de referência e registrar qualidade e recursos.
- **F2 — Aquisição:** permitir que B/C aprendam apenas com o conjunto de treino.
- **F3 — Cristalização:** gerar a habilidade, contrato, testes, proveniência e versão.
- **F4 — Persistência:** encerrar o agente, reiniciar e verificar recuperação por hash e versão.
- **F5 — Transferência:** avaliar A/B/C em instâncias holdout inéditas.
- **F6 — Composição:** avaliar D em tarefas compostas e controles que exigem somente uma habilidade.
- **F7 — Auditoria:** revisão independente de vazamento, resultados, regressões e artefatos.

### 4.3 Famílias de tarefas

Começar com três famílias determinísticas e de baixo custo:

1. **Transformação estruturada:** interpretar e transformar dados com gramática e invariantes definidos.
2. **Diagnóstico de falhas:** identificar causas em fixtures de logs/configurações com causa-raiz conhecida.
3. **Planejamento sob restrições:** produzir sequência válida de operações respeitando dependências, recursos e invariantes.

Cada família deve ter tarefas de treino, holdout de transferência e tarefas compostas. Os geradores devem permitir variações estruturais, não apenas trocar nomes ou valores superficiais.

A dificuldade deve crescer gradualmente. Não misturar tarefas cuja solução depende de conhecimento externo não disponibilizado de forma equivalente a todos os braços.

## 5. Construção de habilidade

Uma habilidade candidata deve conter, no mínimo:

- ID único, nome, versão e hash.
- Problema e domínio de validade.
- Proveniência das experiências que a originaram.
- Pré-condições e pós-condições.
- Tipos e esquema das entradas e saídas.
- Invariantes que devem permanecer verdadeiros.
- Dependências e versões.
- Permissões mínimas e efeitos colaterais.
- Limites de CPU, RAM, tempo, disco e rede.
- Testes positivos, negativos, adversariais e regressivos.
- Casos conhecidos em que deve se abster.
- Evidências, limitações e confiança.
- Procedimento de rollback e estado de promoção.

Uma habilidade não é aprovada porque reproduz o exemplo de treino. Deve passar por testes independentes e holdout. A execução inicial deve ocorrer em fixtures/sandbox, sem segredos, rede ou permissões privilegiadas.

## 6. Contratos de composição

A composição só é válida se cada habilidade expuser um contrato verificável.

Para cada ligação entre habilidades, verificar:

1. Compatibilidade entre saída e entrada.
2. Pré-condições da habilidade seguinte.
3. Preservação de invariantes.
4. Ausência de conflito de permissões.
5. Tratamento de erros, timeout e saída parcial.
6. Limites agregados de recursos.
7. Idempotência ou semântica explícita de repetição.
8. Rastreabilidade de cada resultado intermediário.

Executar também controles negativos: composições incompatíveis devem ser rejeitadas antes da execução, sem efeitos colaterais.

## 7. Métricas

| Métrica | Definição |
|---|---|
| Taxa de sucesso | Tarefas que passam integralmente no oráculo independente / tarefas válidas executadas |
| Transferência absoluta | Sucesso de C em holdout |
| Ganho de transferência | Diferença de C em relação a A no mesmo holdout |
| Ganho de memória | Diferença de B em relação a A |
| Ganho de composição | Diferença de D em relação ao melhor entre A/B/C nas tarefas compostas |
| Regressão | Controles previamente aprovados que passam a falhar |
| Intervenção humana | Número e duração de intervenções necessárias |
| Custo temporal | Tempo total e mediana/p95 por tarefa |
| CPU | Tempo de CPU e utilização, quando disponível |
| Memória | Pico de RSS/working set e memória comprometida, com método declarado |
| I/O | Bytes lidos/escritos e page faults, quando mensuráveis |
| Reutilização | Número de tarefas distintas resolvidas pela mesma versão da habilidade |
| Abstenção correta | Casos sem evidência suficiente em que o agente se recusa a afirmar sucesso |

Reportar numeradores e denominadores, não apenas percentuais. Informar intervalos de confiança ou incerteza e resultados por família. Não ocultar falhas, outliers ou tarefas excluídas.

## 8. Critérios preliminares de decisão

Estes limites são critérios propostos para o piloto, não resultados observados. Devem ser congelados no pré-registro antes da execução.

### H1 — Aquisição

**Aprovação preliminar:**
- Habilidade gerada com contrato e proveniência completos.
- Todos os testes de contrato e regressão passam.
- Persistência e recuperação após reinício verificadas por hash.
- Nenhuma permissão além do mínimo declarado.
- Nenhuma execução privilegiada ou efeito externo não autorizado.

### H2 — Transferência

**Aprovação preliminar:**
- Pelo menos 20 instâncias holdout por família, geradas após congelamento da habilidade.
- C supera A em pelo menos 10 pontos percentuais de sucesso agregado, ou mantém qualidade estatisticamente compatível e reduz custo mediano em pelo menos 20%.
- Nenhuma família apresenta regressão material escondida pela média.
- Nenhum vazamento de holdout identificado.

Se o tamanho amostral não permitir conclusão estatística, classificar como exploratório/inconclusivo, não PASS.

### H3 — Composição

**Aprovação preliminar:**
- Pelo menos 20 tarefas compostas holdout.
- D supera o melhor braço isolado em pelo menos 10 pontos percentuais, ou resolve tarefas compostas que os braços isolados não resolvem, com vantagem reproduzida.
- Controles de composição inválida são rejeitados antes de qualquer efeito.
- Nenhuma regressão nos controles de segurança.

Os limites devem ser revistos antes da execução caso uma análise de poder ou custo mostre que a amostra é insuficiente. Nunca alterá-los depois de observar os resultados sem registrar novo protocolo e nova rodada.

### Gate geral

- **PASS:** H1, H2 e H3 atendidas, evidência reproduzível e auditoria independente sem bloqueadores.
- **PASS_WITH_RESTRICTIONS:** aquisição demonstrada, mas transferência/composição limitadas a domínios explicitamente identificados.
- **INCONCLUSIVE:** amostra insuficiente, incerteza elevada, vazamento suspeito ou evidência incompleta.
- **FAIL:** critérios essenciais falham, há regressão não explicada, vazamento confirmado ou violação de segurança.

## 9. Recursos e operação CPU-first

Não fixar um orçamento universal antes de caracterizar a máquina de teste. Registrar:

- CPU, arquitetura, número de núcleos e threads.
- RAM física e memória livre no início.
- Sistema operacional e versão.
- Espaço livre e tipo de armazenamento.
- Processos concorrentes relevantes.
- Versões de runtime e dependências.

Definir limites explícitos por execução para CPU, RAM, tempo, disco e rede. O piloto deve começar com concorrência 1, fixtures pequenas e workers isolados. Interromper de forma segura ao atingir qualquer limite.

GPU e inferência remota paga não são permitidas como dependências dos braços A–D. Se um modelo local opcional for avaliado futuramente, deverá ser um braço separado, com modelo, licença, footprint e custo registrados.

## 10. Ameaças à validade

- **Vazamento de dados:** treino e teste compartilham exemplos, sementes ou respostas.
- **Memorização superficial:** o holdout difere apenas em nomes ou valores.
- **Oráculo enviesado:** o avaliador favorece a implementação produzida.
- **Ajuste ao benchmark:** o agente ou pesquisador adapta a solução ao conjunto de teste.
- **Confundimento por orçamento:** um braço recebe mais tempo, tentativas ou ferramentas.
- **Viés de seleção:** tarefas difíceis são excluídas após observar falhas.
- **Falsa composição:** a tarefa é resolvida por uma única habilidade ou regra oculta.
- **Persistência enganosa:** o processo mantém estado em memória ou cache após o suposto reinício.
- **Métrica agregada enganosa:** ganhos em uma família escondem regressões em outra.
- **Contaminação externa:** dados ou serviços externos introduzem informação desigual entre braços.

Toda ameaça identificada deve ser registrada com evidência e impacto.

## 11. Artefatos obrigatórios

Guardar em diretório próprio do experimento:

- README.md — escopo, status e instruções de reprodução.
- protocol.md — cópia congelada deste protocolo e versão.
- task-catalog.md — catálogo e critérios das tarefas.
- train-manifest.json — manifesto do conjunto de treino.
- holdout-manifest.json — manifesto protegido, acesso controlado.
- skill-contract.schema.json — esquema do contrato de habilidade.
- baseline-results.jsonl — resultados brutos do braço A.
- memory-results.jsonl — resultados brutos do braço B.
- skill-results.jsonl — resultados brutos do braço C.
- composition-results.jsonl — resultados brutos do braço D.
- resource-metrics.jsonl — amostras de recursos.
- integrity/SHA256SUMS — hashes dos artefatos.
- final-report.md — análise, limitações e veredito.

Não registrar segredos, tokens, dados pessoais ou conteúdo não autorizado. Os resultados brutos devem ser preservados; resumos não os substituem.

## 12. Independência da avaliação

A pessoa/agente que cria a habilidade não deve ser o único avaliador.

A revisão deve:
- verificar a divisão treino/holdout;
- procurar vazamento e atalhos;
- reproduzir os testes com ambiente limpo;
- inspecionar os contratos e permissões;
- recalcular métricas a partir dos dados brutos;
- tentar casos adversariais e contraexemplos;
- verificar hashes e persistência;
- emitir objeções e classificá-las por severidade.

Se não houver avaliador independente, registrar essa limitação e não declarar o gate geral aprovado.

## 13. Segurança e autoridade

- Habilidades novas permanecem experimentais e sem privilégios.
- Execução em sandbox/fixtures, sem acesso a segredos ou produção.
- Rede desabilitada por padrão.
- Allowlist explícita de ferramentas e diretórios.
- Limites de recursos e timeout obrigatórios.
- Toda ação com efeitos externos exige autorização explícita.
- O núcleo de políticas, contenção e auditoria não pode ser modificado pela habilidade que está sendo avaliada.
- Promoção exige revisão, testes, versão e rollback.

## 14. Resultado esperado

O experimento deve produzir uma resposta verificável para cada pergunta:

1. O AURIX consegue extrair uma habilidade de uma experiência?
2. A habilidade sobrevive ao reinício e mantém integridade?
3. Ela transfere competência para instâncias inéditas?
4. A composição acrescenta capacidade mensurável?
5. A melhoria mantém qualidade, segurança e limites de recursos?
6. O resultado foi reproduzido por avaliação independente?

Um resultado negativo é útil: identifica qual parte da tese precisa ser revista. Não é permitido transformar ausência de prova em evidência de sucesso.

## 15. Relação com a visão arquitetural

Este protocolo operacionaliza, em escala pequena, as teses de Inteligência Estrutural Acumulativa e Inteligência Generativa Estrutural.

- **AURIX:** coordena tarefas, memória, habilidades e políticas.
- **Memory Engine:** mantém episódios e conhecimento com proveniência.
- **Skill Engine / Knowledge-to-Skill Compiler:** produz habilidades versionadas.
- **Hypothesis-to-Discovery Engine:** propõe e testa novas estratégias.
- **Reasoning Engine:** escolhe métodos de solução.
- **AZTI:** verifica contenção, integridade, repetibilidade e evidências.
- **HPSI:** permanece opcional e fora do caminho crítico deste experimento.

## 16. Estado e autorização

Estado inicial: **PROPOSED / NOT RUN**.

Este documento não autoriza:
- implementação no núcleo do AURIX;
- integração de HPSI;
- execução em produção;
- alteração autônoma de permissões;
- promoção automática de habilidades;
- alegações de superioridade geral ou AGI.

A próxima decisão, após revisão do protocolo, é autorizar separadamente a implementação de um harness experimental isolado. Só depois de aprovada essa implementação poderá ser iniciada a coleta de resultados.
