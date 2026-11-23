# SPEC-20261123-1613: Backend e frontend só em localhost, sem CORS aberto

**Status:** draft
**Porte:** P
**Owner:** @aliothbl
**Criada:** 2026-11-23 16:13
**Ativada:** —
**Concluída:** —
**Pausada em:** —
**Commit final:** —
**Keywords:** bind, cors, localhost, seguranca, vite-proxy
**Features:** infra
**Branch:** —
**Programa:** —
**Workspace:** —
**Origem:** usuário em 2026-11-23 16:13 (backlog P0 item 1 de docs/DIAGNOSTICO-2026-11-23.md)
**Resumo:** Padrão seguro de rede: backend e Vite escutam em 127.0.0.1 e o frontend fala com a API pelo proxy do Vite, eliminando o CORS `*`.

## Objetivo

Hoje o backend sobe em `0.0.0.0:5001` (`backend/run.py:39`), o Vite roda com `--host` e o CORS aceita qualquer origem (`backend/app/__init__.py:43`). Como não há autenticação, qualquer máquina da rede ou qualquer site aberto no navegador pode acionar a API e gastar créditos de LLM e Zep. A SPEC torna localhost o padrão e remove a necessidade de CORS aberto.

## Escopo

**DENTRO:**
- Padrão de `FLASK_HOST` passa a `127.0.0.1` em `backend/run.py`; continua sobrescrevível por env.
- `frontend/package.json` (`dev`): Vite em `--host 127.0.0.1` em vez de `--host`.
- `frontend/src/api/index.js`: `baseURL` padrão relativo (`''`), usando o proxy `/api` já existente em `frontend/vite.config.js`. `VITE_API_BASE_URL` continua sobrescrevendo.
- Proxy do Vite com alvo `http://127.0.0.1:5001`, para evitar a resolução de `localhost` para `::1`.
- CORS restrito a uma lista configurável (`CORS_ORIGINS`, padrão `http://localhost:3000,http://127.0.0.1:3000`).
- `.env.example` documenta `FLASK_HOST`, `CORS_ORIGINS` e o risco de expor sem autenticação.

**FORA:**
- Autenticação/autorização (SPEC futura, pré-requisito para qualquer exposição em rede).
- Imagem Docker de produção (backlog item 22). O `docker-compose.yml` mantém o comportamento atual, apenas documentado.

## Invariantes

- NUNCA o padrão sem `.env` expõe a API fora do loopback.
- SEMPRE é possível sobrescrever o host por variável de ambiente (Docker precisa de `0.0.0.0` dentro do container).

## Implementação

Trocar os padrões de bind; usar o proxy do Vite (mesma origem para o navegador) para eliminar requisições cross-origin no fluxo normal; manter `flask-cors` só para origens explícitas.

### Modelo de dados

—

<!-- Alternativas: (a) manter CORS e só restringir a origem — rejeitada como solução única porque o proxy já existe e evita CORS por completo; (b) autenticação por token agora — maior esforço, fica para SPEC própria. -->

## Riscos

- O Docker deixa de funcionar se o padrão mudar dentro do container — mitigação: o Dockerfile/compose define `FLASK_HOST=0.0.0.0` explicitamente.
- Streams (`/agent-log/stream`, `/console-log/stream`) via proxy podem sofrer buffering — mitigação: testar os streams do relatório no critério 3.

## Sinais de sucesso

- Fluxo completo (upload → relatório) roda local sem nenhuma porta do MiroFish visível na LAN.

## Critério de aceite

- [ ] `npm run dev` sem `FLASK_HOST` no `.env`: `ss -ltn` mostra 5001 e 3000 só em `127.0.0.1`.
- [ ] `curl -H "Origin: http://evil.example" -i http://127.0.0.1:5001/api/graph/project/list` não retorna `Access-Control-Allow-Origin`.
- [ ] Fluxo da UI (upload, grafo, simulação curta, relatório com streams de log) funciona via proxy, sem erro de CORS no console.
- [ ] Suíte do backend verde (`cd backend && uv run --frozen python -m pytest tests -q -p no:cacheprovider`).
