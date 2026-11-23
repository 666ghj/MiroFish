# Contexto — orçamentos, compactação e pressão

> Referência sob demanda (R.16). Leia ao estourar um orçamento, antes de compactar, ou ao notar pressão de contexto. Não repita o núcleo: docs/RULES.md já chega via brief da sessão.

## Orçamentos por camada (lintados — R.16)

| Camada | Teto | Enforcement |
|---|---|---|
| CLAUDE.md | 6.000 bytes | lint (erro) |
| AGENTS.md | 6.200 bytes (carrega "Sem hooks?" que o CLAUDE dispensa) | lint (erro) |
| docs/RULES.md (núcleo) | 5.000 bytes | lint (erro) |
| digest.md (archive e discard) | 2.000 bytes | lint (erro) |
| SNAPSHOT do journal | primeiras 60 linhas do arquivo | lint (erro) |
| Cápsula por prompt | 800 bytes | por construção (specctl capsule) |
| Retorno de subagente Nível 3 | ≤500 tokens | protocolo em docs/rules/retrieval.md |
| docs/INDEX.md | **sem teto** | gerado (escala com features×SPECs); disciplina por-entrada (1 linha/SPEC) |
| docs/features/<area>.md | **sem teto** | memória viva por área, nº ilimitado; `rollup` é manual/opcional |

**Natureza dos tetos.** CLAUDE/AGENTS/RULES são **sempre-carregados 1×/sessão** (cacheados; re-lidos barato por turno) — o teto ali é orçamento de **ATENÇÃO, não de custo de token**: a camada precisa ficar de alto sinal para o TIER-0 ser respeitado (bloat → skim → bans perdem força). A **cápsula (800B)** é o ÚNICO por-prompt (multiplicado por turno) — o mais sensível. O **digest** é capado por definição (resumo de trabalho encerrado; sem teto vira cópia do archive). Regra: só entra nas camadas capadas o que merece a atenção do modelo em TODO turno; detalhe situacional vai para `rules/*` (gated).

**Sem teto (de propósito).** `INDEX.md` é enumeração **gerada** — cresce com o sistema; capá-la seria erro de categoria (deadlock: gerado não se edita). `features/<area>.md` é **memória viva por área** e o sistema tem features/áreas ilimitadas — capar seria limitar quanto o produto pode acumular. Nesses dois, a disciplina não é byte: é **conteúdo** (INDEX: 1 linha por SPEC; feature: estado atual + decisões vivas em cima). Se o auto-load N1 de uma área pesar demais no seu julgamento, `specctl rollup <area>` desce blocos antigos (íntegros) para `<area>.history.md` — **opcional, seu critério, nada bloqueia**.

## Estouro de orçamento: mover, NUNCA deletar

PROIBIDO deletar contexto rico. OBRIGATÓRIO movê-lo para a camada mais profunda:

- `features/<area>.md` sem teto, mas se o auto-load N1 pesar (seu critério) → `rollup` opcional dos blocos mais antigos para `features/<area>.history.md` (blocos íntegros, com SPEC-id/DEC-id; o vivo retém estado atual + decisões ativas).
- SPEC fechando → `digest.md` concentra o essencial; main+journal ficam íntegros em `docs/archive/` (recuperáveis via docs/rules/retrieval.md).
- SNAPSHOT inchando → detalhe desce para o LOG (append-only); o SNAPSHOT guarda só o estado vigente.

## Unidade de persistência: checkpoint, não "fim de sessão"

Fim de sessão é indecidível sob auto-compact. Persista por marco: ao concluir fase, registrar `[MARCO]`, tomar decisão relevante — e SEMPRE antes de compactar — reescreva o SNAPSHOT e apende no LOG. O hook PreCompact lembra o flush; se o journal não reflete o estado real, escreva PRIMEIRO. Compactar sem flush = perder a sessão.

## Quando compactar (decisão por transição de fase)

| Transição | Compactar? | Por quê |
|---|---|---|
| Pesquisa → plano | SIM | pesquisa é volumosa; o plano é o destilado |
| Plano → implementação | SIM | plano já está em main/journal; libere janela para código |
| Implementação → testes | TALVEZ | mantenha se os testes referenciam código recém-escrito |
| Depuração → próxima fase | SIM | traces de debug poluem o trabalho seguinte |
| MEIO de implementação | NÃO | perder nomes, paths e estado parcial custa caro |
| Após abordagem que falhou | SIM | registre `[tentativa]` no LOG e limpe o beco sem saída |

## O que sobrevive × o que se perde

| Sobrevive | Se perde |
|---|---|
| Tudo em disco: journal, main, features, código, git | Raciocínio e análises não registrados |
| Brief re-injetado (SessionStart roda pós-compact: bans + SNAPSHOT + NOW) | Conteúdo de arquivos já lidos |
| CLAUDE.md / AGENTS.md | Respostas verbais do usuário não copiadas ao journal |
| — | Histórico de tool calls |

Consequência: resposta-chave do usuário, decisão e estado DEVEM estar no journal ANTES do /compact — depois é tarde.

## /compact com sumário direcionado

Nunca compacte "seco". Direcione o que preservar:

```
/compact Foco: SPEC-20260702-1030-parser, fase 3 (validação). Manter: decisão da gramática PEG, paths src/parser/*. Descartar: exploração de regex da fase 1.
```

## Sinais de pressão de contexto

- Re-perguntar o que o usuário já respondeu; reler arquivos já lidos.
- Esquecer classificação R.9, workspace declarado ou bans TIER-0.
- Respostas mais lentas, genéricas ou incoerentes.
- **Sinal automático (v4.1.1):** o guard-write injeta `[contexto] ~Nk tokens (X% da janela)` quando o contexto REAL cruza o limiar (janela: env > `context_window` do manifesto > detecção pelo transcript; re-lembra a cada +60k). Ao vê-lo: siga até a fronteira de fase, faça o flush e compacte direcionado — nunca corte no meio.

Ação: flush do SNAPSHOT → `/compact` direcionado → o brief pós-compact re-ancora a sessão.
