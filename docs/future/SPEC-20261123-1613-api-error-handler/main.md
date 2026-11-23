# SPEC-20261123-1613: Error handler central e fim dos tracebacks nas respostas

**Status:** draft
**Porte:** M
**Owner:** @aliothbl
**Criada:** 2026-11-23 16:13
**Ativada:** —
**Concluída:** —
**Pausada em:** —
**Commit final:** —
**Keywords:** erros, traceback, api, formato-de-resposta, logging
**Features:** infra
**Branch:** —
**Programa:** —
**Workspace:** —
**Origem:** usuário em 2026-11-23 16:13 (backlog P0 item 4 de docs/DIAGNOSTICO-2026-11-23.md)
**Resumo:** Respostas de erro da API passam a ter formato único e sem stack trace; o traceback fica só no log do servidor.

## Objetivo

52 handlers (`api/simulation.py` 30, `api/report.py` 17, `api/graph.py` 5) devolvem `traceback.format_exc()` no JSON, expondo caminhos e internals; a chave do erro varia entre `error` e `message`, e não há tratamento central. A SPEC cria um contrato de erro único, mantém o traceback só no log e corrige o caso observado em que crédito esgotado (`insufficient_quota`) aparece como falha genérica.

## Escopo

**DENTRO:**
- `errorhandler` central no app Flask (`backend/app/__init__.py`) para exceções não tratadas: loga traceback, responde `{"success": false, "error": <mensagem segura>, "code": <slug>}`.
- Helper `error_response(code, message, status)` e substituição dos 52 `traceback.format_exc()` em respostas.
- Mapeamento de erros de provedor LLM: `insufficient_quota` → `llm_quota_exhausted` (402/503 com mensagem clara), rate limit → `llm_rate_limited`, auth → `llm_auth_failed`. Reaproveitar o mapeamento já existente em `graph.py:394-443`.
- Frontend: exibir `error` do novo formato onde hoje lê `error`/`message`.

**FORA:**
- Padronizar respostas de sucesso.
- i18n das mensagens do backend (backlog item 23).

## Invariantes

- NUNCA uma resposta HTTP contém stack trace, caminho de arquivo do servidor ou valor de chave.
- SEMPRE o traceback completo continua no log do servidor.

## Implementação

Error handler + helper; trocar os retornos por grep mecânico arquivo a arquivo; testes com Flask `test_client` forçando exceção em uma rota de cada blueprint.

### Modelo de dados

—

<!-- Alternativas: manter traceback só com FLASK_DEBUG — rejeitada: debug é ligado por engano e o frontend não precisa do trace. -->

## Riscos

- Telas que exibem `message` em vez de `error` perdem a mensagem — mitigação: grep no frontend e critério 4.
- Mudança mecânica em 52 pontos — mitigação: teste de contrato por blueprint e revisão do diff.

## Sinais de sucesso

- Um erro de crédito esgotado aparece na UI como "crédito do provedor de LLM esgotado", e não como falha genérica.

## Critério de aceite

- [ ] `grep -rn "traceback.format_exc()" backend/app/api` só encontra usos em chamadas de log. | verify: `! grep -rn "\"traceback\": traceback" backend/app/api`
- [ ] Teste: exceção forçada em uma rota de cada blueprint retorna o formato padrão, sem stack trace. | verify: `cd backend && uv run --frozen python -m pytest tests -q -p no:cacheprovider`
- [ ] Erro `insufficient_quota` do provedor vira `code: llm_quota_exhausted` com mensagem clara (teste com cliente fake).
- [ ] Mensagens de erro continuam visíveis nas telas de upload, preparação, simulação e relatório. | evidence: manual @aliothbl
