# AURIX — auditoria técnica e lacunas

Data: 2026-10-09  
Repositório auditado: https://github.com/LU9DI/AURIX  
Branch: `main`  
Commit inspecionado: `85eccb368b44ff8f7490340a3288714fc55cb39e`  
Escopo: árvore publicada, recuperação/manifestos, estrutura Python/CI, segurança de pesquisa web, execução de testes, memória e evidências disponíveis.

## Resumo executivo

A restauração dos arquivos está publicada, mas **isso não equivale a uma instalação reproduzível, CI funcional ou liberação pronta para produção**. O projeto continua identificado como release de pesquisa v0.85.0 e a própria documentação declara que não é software autônomo de engenharia pronto para produção.

### Achados prioritários

| ID | Severidade | Achado | Evidência / impacto |
|---|---|---|---|
| AURIX-001 | **Alta** | Falha ao lidar com página bloqueada por `robots.txt` | Em `source/aurix/research.py`, o ramo que registra o bloqueio usa `section` antes de atribuí-la. Reproduzi `UnboundLocalError` com respostas HTTP simuladas. A pesquisa pode falhar inteira em vez de ignorar a página. |
| AURIX-002 | **Alta** | Proteção contra SSRF vulnerável a DNS rebinding | `_assert_public_http_url()` resolve o hostname e verifica IPs públicos, mas o cliente HTTP depois resolve o hostname novamente. A conexão não está presa ao IP validado; um DNS que mude entre validação e conexão pode contornar o controle de endereço. |
| AURIX-003 | **Alta** | Checkout na raiz não é instalável como documentado | `pyproject.toml`, pacote `aurix/`, testes e `README.md` de uso estão em `AURIX-backup-work/source/`, não na raiz. Portanto, comandos documentados como `pip install -e ".[dev]"` e `pytest` executados a partir da raiz não encontram o projeto Python esperado. |
| AURIX-004 | **Alta** | CI do projeto não é descoberta pelo GitHub Actions | O workflow de teste está em `AURIX-backup-work/source/.github/workflows/ci.yml`; o GitHub só descobre workflows em `.github/workflows/` na raiz do repositório. O único workflow efetivo na raiz é o de restauração, não o de testes/lint. |
| AURIX-005 | **Alta** | Documentação raiz contradiz o estado publicado | `README.md` e `RECOVERY_REPORT.md` ainda afirmam que fonte e releases não foram transferidos e que o repositório está vazio. A árvore atual contém a fonte restaurada, histórico compactado e o backup ZIP. Isso induz operadores a erro. |
| AURIX-006 | **Alta** | Suíte completa sem resultado final conclusivo | Foram coletados 292 testes. `compileall` passou, mas a execução completa expirou no ambiente disponível sem resumo final. Não se deve declarar a suíte integral aprovada. A lintagem Ruff também não foi executada porque Ruff não está instalado nesse ambiente. |
| AURIX-007 | **Média** | Memória sem interface de exclusão/expurgo | O protocolo `MemoryStore` expõe `add` e `search`, sem operação de apagar por ID/escopo, limpar ou expirar registros. Isso deixa incompleta a governança de retenção e exclusão de dados, apesar de a arquitetura mencionar comportamento de exclusão. |
| AURIX-008 | **Média** | Execução padrão não é sandbox | `trusted` é o modo padrão para execução/verificação; ele executa testes no host. O modo Docker é opt-in e ainda monta o workspace com escrita. A documentação reconhece essa fronteira. Não usar o modo padrão para código/repositórios hostis. |
| AURIX-009 | **Média** | O workflow de restauração não valida o manifesto antes de publicar | O workflow extrai e faz commit dos arquivos do ZIP, mas não verifica hashes do manifesto antes de aceitar a árvore extraída. Isso reduz a garantia automática de integridade/reprodutibilidade da restauração. |
| AURIX-010 | **Média** | Transporte do provedor compatível pode enviar credencial por HTTP | `OpenAICompatibleProvider` aceita URL configurável e anexa `Authorization: Bearer` sem exigir HTTPS para hosts remotos. Para endpoints remotos em HTTP, a chave e o prompt podem transitar sem criptografia. Endpoints HTTP locais são um caso legítimo e precisam continuar suportados com aviso/validação contextual. |
| AURIX-011 | **Baixa** | Fingerprint de cache usa metadados, não conteúdo | `ResponseCache.workspace_fingerprint()` combina caminho, tamanho e `mtime_ns`, sem hash do conteúdo. Alterações que preservem esses metadados podem não invalidar a chave e permitir resposta terminal obsoleta. |

## Verificações realizadas

- Consultada a árvore recursiva do GitHub: 273 entradas, incluindo fonte, testes, documentação, workflow, backup ZIP e snapshots históricos.
- A fonte publicada inclui 47 módulos Python e 32 arquivos Python de teste; o projeto configura pytest e Ruff em `pyproject.toml`.
- `python -m compileall -q aurix tests`: **passou** (sem erros de sintaxe).
- Coleta pytest: **292 testes**.
- Execução da suíte integral: **inconclusiva** — o processo expirou antes do resumo final. Não é um resultado de aprovação.
- Ruff: **não executado**; o binário não está instalado no ambiente desta auditoria.
- Backup consolidado local: manifesto SHA-256 conferido, **183 entradas verificadas, 0 ausentes e 0 divergentes**.
- ZIPs históricos locais: **84 arquivos**, todos passaram `ZipFile.testzip()`.
- O manifesto/ZIP local confirma integridade dos artefatos locais verificados; isso não substitui uma verificação automatizada de cada arquivo publicado no GitHub contra o manifesto no próprio workflow.
- Reproduzido com HTTP simulado o defeito de `robots.txt`: `UnboundLocalError: cannot access local variable 'section' where it is not associated with a value`.
- O run do workflow de restauração no GitHub aparece como `success`; isso comprova a execução bem-sucedida da restauração, **não** a aprovação dos testes do produto.

## Lacunas de produto e validação

1. **Publicação/instalação:** decidir e aplicar uma estrutura canônica (fonte na raiz ou configuração de monorepo documentada), atualizar os comandos de instalação e remover a divergência dos documentos de recuperação.
2. **CI:** mover/configurar o workflow para `.github/workflows/ci.yml` na raiz e executá-lo em push e pull request; fazer lint e suíte integral serem gates reais.
3. **Pesquisa segura:** corrigir a ordem de construção de `section`; validar URLs e destinos de rede no momento da conexão, sem uma segunda resolução DNS não confiável; adicionar testes de bloqueio de robots, redirecionamento, IP privado, DNS mutável e resposta oversized.
4. **Execução de código:** manter o aviso explícito de que `trusted` não isola o host; para uso com código não confiável, tornar isolamento forte o caminho recomendado e documentar os limites de daemon, kernel, imagem e volume gravável.
5. **Privacidade de memória:** acrescentar exclusão verificável, retenção/expiração e testes para SQLite e PostgreSQL/Neon; documentar backup e eliminação dos registros.
6. **Integridade da recuperação:** verificar o manifesto antes do commit e gerar evidência de hashes/contagens no run; definir limites de tamanho descompactado e quantidade de entradas.
7. **Reprodutibilidade:** executar testes e Ruff no Python suportado (Python 3.11+, conforme o projeto), publicar resultados e separar testes unitários rápidos dos testes de integração demorados.
8. **Provedores remotos:** avisar ou bloquear credenciais em endpoints HTTP não locais; testar redaction, timeout, respostas malformadas e falhas de conexão.
9. **Cache:** considerar hash de conteúdo para arquivos relevantes ou documentar o fingerprint como heurístico, não garantia de invalidação.

## Ordem recomendada de correção

**P0 — antes de confiar na pesquisa web:** AURIX-001 e AURIX-002.  
**P1 — antes de declarar a publicação pronta para desenvolvimento:** AURIX-003, AURIX-004, AURIX-005, AURIX-006 e AURIX-009.  
**P2 — antes de usar em equipes/dados sensíveis:** AURIX-007, AURIX-008 e AURIX-010.  
**P3 — robustez/eficiência:** AURIX-011.

## Limitações desta auditoria

Esta é uma auditoria estática e de execução limitada sobre o snapshot publicado v0.85.0 e o backup local disponível. Não foi possível concluir a suíte completa nem executar Ruff nesta sessão; não foi feita auditoria dinâmica com modelo real, provedor remoto, Docker real, PostgreSQL/Neon ou REA externo. Os riscos identificados devem ser tratados como pendências abertas até correção e teste de regressão. Não foram feitas alterações no código do produto nesta auditoria.
