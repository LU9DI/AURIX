# AURIX — Caderno de Hipóteses para Autonomia, Aprendizado e Eficiência em CPU

**Status:** hipóteses de pesquisa; não são funcionalidades implementadas nem resultados comprovados.  
**Escopo:** registrar e organizar as 11 linhas de investigação propostas para o AURIX.  
**Princípio:** execução local e CPU-first, sem dependência obrigatória de APIs pagas, tokens de terceiros ou GPU.  
**Stack de referência:** Rust e Node.js 20+, respeitando as versões efetivamente suportadas pelo repositório.

---

## 1. Objetivo e limites

Investigar como combinar computação simbólica, busca heurística, síntese de programas, memória de experiências, otimização clássica e agentes especializados para construir um sistema cada vez mais autônomo.

A meta de longo prazo é ampliar a capacidade do AURIX em tarefas reais de pesquisa, programação, engenharia reversa, automação e coordenação de bots. Comparações com Claude Code, DeepSeek e outros sistemas devem ser feitas por benchmarks reproduzíveis, sem presumir equivalência geral.

**Distinções importantes:**
- Autorreprodução de artefatos não é sinônimo de inteligência.
- Memória de experiências não é treinamento de pesos de uma rede neural.
- Aprendizado por reforço só é útil quando estados, ações, recompensas e limites estão bem definidos.
- CPU-only e ausência de API paga não significam custo computacional zero.
- Autonomia deve ser limitada por permissões, orçamento de recursos, trilhas de auditoria e possibilidade de interrupção.
- Nenhum módulo experimental deve modificar ou substituir automaticamente o runtime principal.

## 2. Hipóteses do primeiro conjunto

### H1 — Programação genética baseada em byte-patches e ASTs

**Hipótese:** programas podem ser representados como genomas e evoluídos por mutação, crossover, seleção e avaliação de fitness, usando CPU.

**Abordagem proposta:**
- Manter biblioteca local compacta de estruturas lógicas, padrões e transformações verificadas.
- Preferir ASTs tipadas e transformações semânticas a mutações arbitrárias de bytes.
- Aplicar mutação de constantes, operadores, subárvores e crossover entre estruturas compatíveis.
- Avaliar candidatos por testes, invariantes, regressões, custo e generalização.
- Preservar seeds, histórico de operadores e resultados para reprodução.

**Experimento inicial:** funções matemáticas pequenas com casos de treino, validação e teste inéditos.

**Riscos e limites:** mutação de bytes tende a produzir muitos candidatos inválidos; passar em poucos testes não prova correção geral. Código gerado não deve ser executado sem isolamento. O fitness deve priorizar correção, não velocidade isolada.

### H2 — SVM e algoritmos lineares para heurísticas

**Hipótese:** classificadores clássicos e estatísticas simples podem resolver tarefas específicas de triagem sem Transformers.

**Sinais candidatos:** entropia de Shannon por bloco, frequência de padrões e instruções, características estruturais de arquivos e CFGs, contagens de chamadas e metadados observáveis.

**Abordagem proposta:** estabelecer primeiro baselines de regras e estatística; depois comparar SVMs e modelos lineares implementados ou suportados por crates Rust, como linfa ou smartcore, após verificar manutenção, licença e compatibilidade.

**Riscos e limites:** entropia alta não prova malware; baixa entropia não prova segurança. Classificadores exigem dados rotulados, avaliação de falsos positivos/negativos e monitoramento de drift. Não usar a saída como única base para bloquear nós ou apagar arquivos.

### H3 — Autômatos celulares para orquestração

**Hipótese:** regras locais simples podem coordenar bots ou nós em uma malha distribuída sem um controlador central pesado.

**Abordagem proposta:** modelar cada nó/bot como agente com estado explícito; definir vizinhança, transições e mensagens permitidas; simular sobrecarga, falhas, desconexões, replicação e recuperação; medir convergência, estabilidade, tráfego, fairness e custo por nó.

**Riscos e limites:** comportamento emergente não garante comportamento desejável. O(1) por nó só vale sob hipóteses restritas sobre vizinhança e estado; o custo global pode crescer com a rede. A replicação deve obedecer a quotas e autorização.

### H4 — Geração e compilação dinâmica de bots via WASM/JIT

**Hipótese:** uma biblioteca de blocos lógicos e módulos WASM pode permitir criar bots pequenos sem gerar aplicações completas.

**Abordagem proposta:** compor capacidades a partir de templates e componentes verificados; gerar módulos WASM ou scripts restritos; aplicar limites de memória, combustível/instruções, tempo, syscalls e acesso à rede/arquivos; assinar artefatos, registrar origem, versão e permissões; testar compatibilidade e rollback antes da distribuição.

**Riscos e limites:** WASM não fornece isolamento total por si só; a configuração do runtime e das capabilities é decisiva. JIT não é sempre mais rápido nem mais econômico. Não injetar código arbitrário no processo principal.

### H5 — Q-Learning tabular

**Hipótese:** políticas pequenas de decisão podem ser aprendidas por tabelas Q em problemas discretos e limitados.

**Possíveis domínios:** seleção de rotas, escalonamento de tarefas, política de cache e alocação de recursos.

**Abordagem proposta:** definir formalmente estados, ações e recompensas; usar ambiente simulado antes de qualquer ação em rede ou sistema real; comparar com políticas fixas e heurísticas; limitar exploração, memória, tempo e frequência de atualização; registrar versões da política e permitir rollback.

**Riscos e limites:** recompensas mal projetadas geram políticas ruins; Q-Learning não garante ótimo global em qualquer ambiente. Não treinar políticas para contornar controles de segurança, firewalls ou restrições de terceiros.

### H6 — Índices simbólicos, grafos de conhecimento e busca heurística

**Hipótese:** índices invertidos, BM25, relações explícitas e grafos podem recuperar conhecimento útil sem embeddings.

**Abordagem proposta:** extrair termos, símbolos, entidades, versões, relações e proveniência; criar índices invertidos e busca lexical BM25; construir relações tipadas em grafo quando houver evidência suficiente; usar BFS/A* para consultas de caminho e descoberta de relações; registrar fonte, data, licença e confiança de cada afirmação.

**Riscos e limites:** grafos refletem a qualidade da extração; relações incorretas propagam erros. A busca não é automaticamente determinística ou livre de alucinações: a resposta deve distinguir evidência, inferência e ausência de dados. Árvores de sufixos são uma opção especializada, não a escolha padrão para toda documentação.

## 3. Hipóteses do segundo conjunto

### H7 — Quines e autorreprodução controlada

**Hipótese:** o AURIX pode gerar uma representação serializada de si mesmo, reproduzir artefatos e construir versões experimentais a partir de transformações verificadas.

**Conceitos:** Quine (programa que emite sua própria representação); manifesto de build (fontes, dependências, toolchain, configuração e hashes); atualização imutável (produzir novo artefato ao lado do atual, nunca sobrescrevê-lo durante a execução); verificação por testes, assinatura, proveniência e comparação com baseline; ativação mediante aprovação explícita ou política administrativa previamente autorizada, com rollback.

**Limite de segurança obrigatório:** não implementar propagação não autorizada, persistência oculta, evasão de controles, auto-instalação em máquinas de terceiros ou substituição silenciosa do binário em execução. O experimento deve limitar-se à reprodução e atualização consentida do próprio ambiente de teste.

**Critério de sucesso:** reproduzir builds de forma determinística e demonstrar que uma versão candidata só é ativada após verificações e autorização.

### H8 — Sistemas imunológicos artificiais (AIS)

**Hipótese:** mecanismos inspirados em seleção clonal e detecção de anomalias podem apoiar defesa adaptativa de uma malha P2P.

**Abordagem proposta:** definir sinais observáveis e baseline por nó; detectar desvios com regras e modelos estatísticos locais; gerar regras candidatas de mitigação; testar regras em modo observação/simulação antes de aplicá-las; distribuir regras assinadas, versionadas, com expiração e rollback; isolar somente com critérios auditáveis e mecanismo de contestação/reintegração.

**Riscos e limites:** falsos positivos podem isolar nós legítimos. Não permitir que bots criem e propaguem regras de firewall irrestritas. Respostas devem respeitar autorização administrativa, princípio do menor privilégio e limites de impacto.

### H9 — Redução de grafos de opcodes e comparação de CFGs

**Hipótese:** grafos de fluxo de controle e características de instruções podem ajudar a reconhecer funções e padrões de software sem embeddings.

**Abordagem proposta:** extrair CFGs de binários com ferramentas apropriadas; normalizar registradores, endereços e nomes quando possível; representar blocos básicos, arestas, chamadas e padrões de instrução; comparar fingerprints, subgrafos e propriedades estruturais; manter proveniência, arquitetura, compilador e nível de otimização; usar matching aproximado quando isomorfismo exato for caro.

**Riscos e limites:** ofuscação, otimização, arquitetura e compilador alteram grafos. Subgraph isomorphism pode ser computacionalmente caro. Reduzir loops a equações simples não é geralmente seguro nem preserva semântica. Identificação deve apresentar score e evidências, não certeza indevida.

### H10 — RIL: linguagem intermediária reflexiva/DSL compacta

**Hipótese:** uma DSL pequena, tipada e específica do domínio pode representar tarefas de bots de forma compacta, auditável e portátil.

**Abordagem proposta:** definir gramática e bytecode versionados; criar conjunto fechado de instruções e tipos; validar programas antes da execução; implementar interpretador Rust determinístico; definir capabilities explícitas para leitura, escrita, rede, criptografia e acesso a recursos; aplicar limites de passos, memória, tempo e tamanho; assinar pacotes e registrar versão, origem e permissões.

**Exemplo conceitual:** READ_BLOCK -> VALIDATE_LENGTH -> COMPUTE_HASH -> EMIT_RESULT.

**Riscos e limites:** instruções de rede, descriptografia e escrita precisam de autorização e semântica rigorosa. O runtime deve negar por padrão operações não declaradas. Compactação não substitui segurança nem validação.

### H11 — Ant Colony Optimization (ACO) para descoberta e pesquisa

**Hipótese:** feromônios virtuais podem priorizar fontes e caminhos de pesquisa com histórico de utilidade.

**Abordagem proposta:** definir grafo de fontes, repositórios, documentos e relações; atualizar pesos com utilidade observada, qualidade, frescor e confiabilidade; aplicar evaporação para reduzir peso de fontes antigas ou pouco úteis; explorar alternativas para evitar concentração prematura; deduplicar descobertas e manter proveniência; respeitar limites de taxa, robots.txt, termos de serviço, autenticação e licenças.

**Riscos e limites:** popularidade não equivale a verdade; feedback pode criar bolhas e reforçar fontes ruins. O algoritmo deve manter exploração, diversidade e penalidades para conteúdo duplicado ou não verificável.

## 4. Integração conceitual

As hipóteses podem ser organizadas em cinco planos:

1. **Síntese e evolução:** H1, H4, H7 e H10.
2. **Percepção e classificação:** H2, H8 e H9.
3. **Memória e conhecimento:** H6 e a memória de experiências associada a H1.
4. **Decisão e coordenação:** H3, H5 e H11.
5. **Verificação e governança:** camada transversal de testes, isolamento, assinatura, auditoria, permissões e rollback.

Fluxo de referência:

Descoberta -> Extração -> Indexação -> Hipótese -> Síntese -> Verificação -> Memória -> Distribuição autorizada -> Monitoramento

Nenhuma etapa deve converter automaticamente uma hipótese em regra de produção.

## 5. Ordem recomendada de experimentação

| Fase | Experimento | Justificativa |
|---|---|---|
| E0 | AST + programação genética + fitness | Testa síntese verificável em CPU |
| E1 | Memória de experiências + BM25 | Mede reutilização e generalização |
| E2 | DSL/RIL interpretada | Estabelece formato seguro e compacto para bots |
| E3 | Índice simbólico e grafo de conhecimento | Base para pesquisa e recuperação |
| E4 | CFG fingerprints e matching | Pesquisa aplicada à engenharia reversa |
| E5 | Heurísticas lineares/SVM | Classificação com baselines mensuráveis |
| E6 | Q-Learning tabular | Decisão em simulador controlado |
| E7 | ACO para priorização de fontes | Pesquisa adaptativa com proveniência |
| E8 | AIS em modo observação | Detecção e mitigação sem bloqueio automático |
| E9 | Autômatos celulares | Coordenação distribuída simulada |
| E10 | Quine e pipeline de atualização | Reprodutibilidade e evolução controlada |
| E11 | WASM/JIT e fábrica de bots | Só após DSL, segurança e verificação |

A ordem pode mudar diante de evidências, mas não se deve pular as etapas de segurança e validação.

## 6. Protocolo de avaliação comum

Cada experimento deve registrar: hipótese e previsão antes do teste; commit/versão e ambiente; hardware, SO, toolchain e dependências; seed e parâmetros; dataset e licença; baseline comparável; casos de treino, validação e teste inéditos; taxa de sucesso e falhas; falsos positivos e falsos negativos quando aplicável; tempo, CPU, pico de RAM e armazenamento; tráfego de rede quando aplicável; reprodutibilidade; limitações e decisão de continuar, revisar ou abandonar.

Resultados devem ser repetidos com múltiplas seeds quando isso fizer sentido. Não declarar superioridade sem comparação justa e estatisticamente adequada.

## 7. Princípios de segurança e governança

- Desenvolvimento experimental isolado do runtime principal.
- Menor privilégio por padrão.
- Sandboxes e limites de recursos para código e bots.
- Sem execução arbitrária de código recebido pela rede.
- Sem propagação ou autorreplicação para máquinas sem autorização explícita.
- Sem evasão de firewall, controles de acesso ou monitoramento.
- Atualizações assinadas, verificadas, versionadas e reversíveis.
- Ações de alto impacto exigem aprovação administrativa.
- Logs auditáveis e explicabilidade operacional.
- Quotas para CPU, RAM, disco, rede e quantidade de agentes.
- Respeito a licenças, políticas de acesso e termos das fontes consultadas.

## 8. Definição de sucesso de longo prazo

O AURIX só deve ser considerado mais capaz quando demonstrar, em tarefas novas e reproduzíveis: maior taxa de resolução correta; menor número de regressões; melhor reutilização de conhecimento validado; autonomia operacional dentro de limites definidos; eficiência mensurada de CPU, RAM, disco e rede; capacidade de explicar evidências e incertezas; atualização segura e reversível; resultados comparáveis a baselines fortes.

**Conclusão:** estas 11 linhas são um programa de pesquisa para construir componentes especializados e verificáveis. Nenhuma, isoladamente, substitui um modelo de fronteira em todas as tarefas. A hipótese estratégica é que a combinação de síntese simbólica, memória, busca, verificadores e agentes pequenos possa produzir capacidades úteis com custo marginal baixo e sem dependência obrigatória de APIs pagas ou GPUs.
