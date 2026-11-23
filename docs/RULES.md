# RULES — Sistema SPEC-driven v4 (núcleo)

Schema: sdd-4.0 · revisão do template: a do manifesto `docs/.spec-system.json` (fonte única). Detalhe operacional em `docs/rules/*.md` — ler SÓ no momento do uso (mapa no fim).

## Premissa

1. Docs são para a IA reter contexto entre sessões: densos, imperativos, auto-contidos. Densidade > enxutidão; rollup, nunca corte.
2. Única exceção: `main.md` de cada SPEC é o CONTRATO validado por humano (R.6.2).
3. Contexto é ENTREGUE por hooks (brief/cápsula), não lido por ritual; regra sem mecanismo é bug.

## Regras R.1–R.17 (com sub-regras 6.1/6.2)

| R | Regra | Detalhe |
|---|---|---|
| 1 | ID = `SPEC-YYYYMMDD-HHMM-slug`, timestamp real via `specctl new`; PROIBIDO sequencial/reuso | formats |
| 2 | `docs/active/` SEMPRE vazio em `main` — gate no CI (`audit --main-gate`) | ci |
| 3 | Canônicos: `main.md`+`journal.md`; `digest.md` no fechamento; opcionais de porte declarados | formats |
| 4 | Toda SPEC vincula ≥1 feature, validada contra TAXONOMY.md | formats |
| 5 | Ciclo de vida: NUNCA deletar; discard/pause preservam; exceção única: redação R.15 | lifecycle |
| 6 | Timestamp `YYYY-MM-DD HH:MM` em TODA atualização (fonte: NOW injetado; ausência = ERRO) | formats |
| 6.1 | Progresso em tempo real no main.md (QA/verify marcam critérios; nunca batch); todo artefato de trabalho tem contrapartida no journal | lifecycle |
| 6.2 | Deferir/adiar/aceitar-incompleto/reduzir escopo SÓ com autorização explícita do usuário (citação; marcador `[aceito-incompleto]`) — nunca unilateral, em qualquer momento | lifecycle |
| 7 | Features atualizadas ao arquivar, validadas por CONTEÚDO no diff do PR | lifecycle |
| 8 | Isolamento: journal de outra SPEC e archive/ negados por hook; histórico via subagente/digest | retrieval |
| 9 | Classificar todo prompt na 1ª linha da resposta: `[continuidade: SPEC-x]` \| `[nova]` \| `[livre]` | lifecycle |
| 10 | Leitura livre com orçamentos (policy `strict` no manifesto reativa confirmação de N1) | context |
| 11 | Ativação cria claim `docs/claims/SPEC-<id>.md`, visível em main | team |
| 12 | Temporários em `tmp/` da SPEC ou `.scratch/`; evidência persistente em `evidence/` | formats |
| 13 | Área existente na TAXONOMY = vínculo automático; área NOVA = confirmação do usuário | lifecycle |
| 14 | Programa = manifesto único `docs/programs/<slug>.md`; Bloqueia/ordem são DERIVADOS | programs |
| 15 | Segredo em docs/ PROIBIDO → `<REDACTED:tipo>`; secret-scan; exceção auditada ao append-only | verification |
| 16 | Orçamentos lintados só nas camadas sempre-carregadas (CLAUDE/AGENTS/RULES) + digest; estourou → mova p/ camada mais profunda. INDEX (gerado) e features (memória viva, nº ilimitado) NÃO têm teto | context |
| 17 | Commit sob SPEC ativa leva trailer `Spec: SPEC-<id>` | lifecycle |

> **R.6 · porte e evidência:** Porte P fecha critérios com timestamp+commit via `specctl check`; `verify:`/`evidence/` são ferramentas de M/G. Detalhe: rules/verification.md.

## Níveis de leitura (ordem recomendada + orçamento)

| N | Fonte | Orçamento | Quando |
|---|---|---|---|
| 0 | brief (SessionStart) + cápsula (por prompt) | ~3k tok / 800 B | automático (hook) |
| 0.5 | ARCHITECTURE.md, CONSTITUTION.md | ~1,8k tok | orientação transversal |
| 1 | features/<area>.md + main.md da SPEC | sem teto (rollup opcional) | continuidade: auto-load |
| 2 | journal.md — SNAPSHOT (60 primeiras linhas) antes do LOG | SNAPSHOT ≤60 linhas | retomada/detalhe |
| 3 | archive/ e discard/ via subagente → digest | retorno ≤500 tok | raciocínio histórico |

## Orçamentos por arquivo (R.16 — lint)

| Arquivo | Teto |
|---|---|
| CLAUDE.md | 6.000 B · AGENTS.md 6.200 B |
| docs/RULES.md (este) | 5.000 B |
| digest.md | 2.000 B |

`INDEX.md` (gerado, escala) e `features/<area>.md` (memória viva, nº ilimitado) **não têm teto**. `specctl rollup <area>` enxuga o auto-load N1 quando você quiser — opcional, nada bloqueia. Detalhe: rules/context.md.

## Quando ler o quê (docs/rules/)

- Criar/editar artefato (main, journal, digest, feature, prd, techspec, tasks, claim, programa, TAXONOMY, importação) → `formats.md`
- Transição de estado: criação, ativação, fechamento, descarte, pausa, retomada, importar → `lifecycle.md`
- Compactação, pressão de contexto, orçamento estourado → `context.md`
- Histórico N3 (archive/discard) → `retrieval.md`
- Verificação: `verify:`, gate build→test→secrets, graders → `verification.md`
- Programa/DAG entre SPECs → `programs.md`
- Time: claims, colisões, worktrees, onboarding → `team.md`
- Harness prd / workspace externo → `interop.md`
- Gates de CI → `ci.md`
