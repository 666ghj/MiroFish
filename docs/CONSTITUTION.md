# CONSTITUTION.md — princípios do projeto

> Orçamento-alvo: ≤2.400 bytes. Princípios INEGOCIÁVEIS que valem para TODA SPEC.
> Entrada nova = decisão humana explícita. Gotcha citado por ≥3 SPECs pode ser promovido para cá no fechamento (docs/rules/lifecycle.md).
> Formato: `- P-<n> — princípio em 1-2 linhas (origem, YYYY-MM-DD)`

## Princípios

- P-1 — Analisar antes de modificar: nenhuma mudança de comportamento sem SPEC aprovada; mudança não pedida é regressão (plano de modernização, 2026-11-23)
- P-2 — Nenhum segredo em código, docs ou logs; chaves só no `.env` ignorado pelo Git; docs usam `<REDACTED:tipo>` (R.15) (plano de modernização, 2026-11-23)
- P-3 — Serviços locais escutam só em 127.0.0.1; expor na rede exige SPEC com autenticação (diagnóstico 2026-11-23, P0)
- P-4 — Toda melhoria tem critério verificável e medição antes/depois; suíte do backend verde é o piso (baseline: 129 passed em 7657031) (plano de modernização, 2026-11-23)
- P-5 — Experimentos do laboratório ficam isolados (branch, config ou flag), nunca alteram o comportamento padrão sem SPEC (plano de modernização, 2026-11-23)
