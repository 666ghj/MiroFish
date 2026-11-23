# AGENTS.md — mirofish

> Regra dura de posicionamento: este bloco imperativo fica SEMPRE no TOPO, antes de qualquer outra seção. `specctl entrypoints` garante isso em regeneração/merge.

## HARD BANS (TIER-0) — valem em TODA resposta

1. **R.6.2** — só o USUÁRIO aceita entrega incompleta, defere ou adia (qualquer "deixar pra depois", em QUALQUER momento) — NUNCA a IA por conta própria. PERGUNTE item a item (implementar agora / SPEC nova / aceitar gap), com citação do usuário.
2. **LOG append-only** — NUNCA editar entradas antigas do `## LOG` do journal.md; correção = nova entrada.
3. **`docs/active/` VAZIO em `main`** — SPEC ativa vive só em branch (CI bloqueia).
4. **Temporários na pasta da SPEC** — `tmp/` (descartável) ou `evidence/` (persistente); sem SPEC → `.scratch/`. Nunca na raiz.
5. **PROIBIDO varrer `scripts/specctl.mjs` ou re-ler `docs/rules/*` só para "garantir compliance"** — os gates dizem o que falta (`close <id> --dry`). Ler a rule DA TAREFA no momento do uso é o caminho certo, não viola este ban.

**R.9 — 1ª linha de TODA resposta = classificação:** `[continuidade: SPEC-x]` (trabalho de SPEC existente) | `[nova]` (demanda que muda comportamento/código do produto → exige SPEC) | `[livre]` (pergunta, análise, leitura, config de ferramenta, bump de harness — nada que altere o produto; sem SPEC). Ambíguo? PERGUNTE.

## Sem hooks? (CLIs sem suporte)

- Início de CADA sessão: rode `node scripts/specctl.mjs brief` e cole o output.
- Gatilhos `/spec`: "inicie uma spec: <demanda>" · "feche a spec" · "status das specs" · "pause/retome a SPEC-x".
- Antes do PR: `specctl lint` e `audit`. O CI (docs-gate) é o piso universal.

## Estrutura docs/

- `docs/RULES.md` — núcleo do processo (R.1–R.17); detalhe situacional em `docs/rules/*`
- `docs/features/<area>.md` — memória viva por área · `docs/INDEX.md` — mapa (GERADO)
- `docs/active|future|archive|discard/SPEC-<ts>-<slug>/` — main.md (contrato) + journal.md (SNAPSHOT + LOG)
- `docs/claims/` — trabalho em voo visível em main · `docs/programs/` — DAGs de SPECs · `docs/PROGRAMS.md` (GERADO) + `docs/ROADMAP.md` — o que pegar a seguir (`specctl next`) · `docs/DEFERRED.md` (GERADO) — deferidos R.6.2
- `docs/TAXONOMY.md` — áreas canônicas · `docs/ARCHITECTURE.md` — mapa região→feature
- `docs/CONSTITUTION.md` — princípios · manifesto: `docs/.spec-system.json`

## Comandos

- test: `cd backend && uv run --frozen python -m pytest tests -q -p no:cacheprovider`
- dev: `FLASK_HOST=127.0.0.1 npx concurrently -k -n backend,frontend "npm run backend" "cd frontend && npx vite --host 127.0.0.1"`

Labels `test/typecheck/lint/dev/e2e` espelhados em `docs/.spec-system.json` — CI e `verify:` consomem de lá; não hardcode.

## Skills e quando disparar

| Situação | Skill |
|---|---|
| Implementar contra lib/framework/API externa cuja API atual você não domina | **Context7 MCP** — confirme assinatura/versão antes de codar (se indisponível: vendor docs / WebSearch) |
| UI / frontend / estilização | frontend-design (se instalada) |
| Porte G — fase PRD (se pipeline instalado) | cria-prd |
| Fases seguintes (se instalado) | cria-techspec → criar-tasks → executar-task → executar-qa/review/bugfix |

## Mapa de referências — ler SÓ no momento do uso

`docs/rules/`: formats (criar/editar artefato) · lifecycle (transições de ciclo de vida) · programs (DAG de SPECs) · interop (workspace externo / pipeline prd) · context (compactação/orçamentos) · retrieval (archive N3) · verification (`verify:` e gates) · team (claims/multi-dev/onboarding) · ci (gates de CI).

<!-- projeto:início -->
## Projeto

MiroFish (fork de 666ghj/MiroFish): motor de previsão por simulação multiagente. Pipeline de 5 etapas — documento → ontologia/grafo (Zep Cloud) → personas → simulação social OASIS (Twitter+Reddit em subprocesso) → relatório ReAct + chat com agentes. Diagnóstico completo: `docs/DIAGNOSTICO-2026-11-23.md`.

**Stack:** Python 3.11–3.12 + Flask (backend/, uv) · camel-ai/camel-oasis · zep-cloud 3.25 · LLM compatível OpenAI (`LLM_*`, opcional `LLM_BOOST_*` só p/ Reddit) · Vue 3 + Vite (frontend/) · estado em arquivos sob `backend/uploads/` (sem banco).

**Gotchas:** `.env` na raiz com `override=True`; placeholders em `LLM_BOOST_*` quebram o Reddit; memória dos agentes sem limite estoura 128k tokens em runs longos; backend padrão em 0.0.0.0 sem auth (rodar com `FLASK_HOST=127.0.0.1`); logs e comentários majoritariamente em chinês.
<!-- projeto:fim -->

---
GERADO por `specctl entrypoints` — edite apenas o bloco projeto (entre marcadores).
