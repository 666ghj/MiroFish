# Formatos literais (rules/formats.md)

> Ler ao criar/editar artefato. Campos/marcadores/ordem LITERAIS (`specctl lint` valida): `**Campo:**` inicia linha; timestamp `YYYY-MM-DD HH:MM` (NOW); paths `/`. Pipeline G: rules/formats-pipeline.md.

## 1. `main.md` — CONTRATO humano-validado

```markdown
# SPEC-<YYYYMMDD-HHMM>: <Título>

**Status:** draft | active | paused | done | discarded
**Porte:** P | M | G
**Owner:** @handle
**Criada:** YYYY-MM-DD HH:MM
**Keywords:** a, b
**Features:** feat-1, feat-2
**Resumo:** 1 frase.

## Objetivo
2-3 frases: o quê e por quê.

## Escopo
**DENTRO:**
- item

**FORA:**
- item

## Invariantes
- SEMPRE/NUNCA <propriedade que vale antes/durante/depois>.  (linha-vermelha; ≠ critério de fim)

## Implementação
abordagem em alto nível (G: detalhe fino em techspec.md).
### Modelo de dados
entidades/campos tocados; "—" se não há mudança de dados.
<!-- Alternativas (M/G): abordagens rejeitadas + porquê; decisão irreversível = [irreversível] -->

## Riscos
- risco — mitigação: como.  (contrato ESTÁVEL; "—" se trivial)

## Sinais de sucesso
- <resultado observável — cumpriu o PROPÓSITO, não só a corretude>.  (P: 1 linha)

## Critério de aceite
- [ ] Critério (gramática por porte — §2)
```

- Obrigatórios (lint): 7 campos + Objetivo, Escopo (DENTRO/FORA), `## Implementação`, Critério de aceite. **Sugeridas todo porte** (scaffold, não-lintadas): `## Invariantes` (SEMPRE/NUNCA — linhas-vermelhas que qualquer mudança futura pode violar), `### Modelo de dados`, `## Riscos`, `## Sinais de sucesso` (resultado/valor, não só corretude), e o hint `Alternativas` (rejeitadas + porquê; `[irreversível]` = porta de mão-única). Tudo CONTRATO estável. NÃO ponha Plano/Decisão/progresso no main — fases vão no SNAPSHOT, decisões no LOG `[decisão]`; aqui duplicaria. `specctl new` cria os campos, transições preenchem, `—`=vazio. Ponteiros: formats-pipeline.md.

## 2. Critério de aceite — gramática POR PORTE

```markdown
- [ ] <texto> ← P: specctl check <id> <n>
- [ ] <texto> (cobre RF-3) | verify: `<cmd>` ← M/G: specctl verify <id>
- [ ] <texto> | evidence: manual @usuario ← grader humano
- [x] <texto> (2026-07-02 15:30, commit `abc1234`, verify: exit 0)
- [ ] <texto> [aceito-incompleto: "<citação literal do usuário>" 2026-07-02 15:30]
```

- `[x]` gravado pela FERRAMENTA (`check`/`verify`) — "verify: exit 0" à mão = spoofing.
- `(cobre RF-n)` obrigatório quando `prd.md` existe (lint valida cobertura).
- `[x]` sem timestamp = ERRO; sem evidência = ERRO em archive. `[aceito-incompleto: ...]` = única forma de arquivar com `[ ]` (R.6.2 — rules/lifecycle.md).

## 3. `journal.md`

```markdown
# Journal — SPEC-<YYYYMMDD-HHMM>

## SNAPSHOT (sobrescrever — cabe nas 60 primeiras linhas)
**Última atualização / Onde tô / Próximo passo / Última decisão / Bloqueio atual / Se retomar, ler:** (1 linha cada)
### Fases — tabela: # | Descrição | Status | Atualizado
### Fatos confirmados / Inferências prováveis / Dúvidas em aberto — anti-alucinação: separe SABIDO de CHUTE de EM-ABERTO; nunca trate inferência como fato
### Respostas-chave · ### Tentativas que falharam · ### Arquivos tocados · ### Onde parei · ### Sessões (máx 5 + 1 agregada)

## LOG (append-only — NUNCA editar entradas antigas)
## YYYY-MM-DD HH:MM — [tipo] Título
Corpo livre.
```

- **Entrada nova no LOG = `specctl log <id> <tipo> "título" [--stdin|--body-file <f>]`** — nunca Edit direto (ferramenta appenda ⎿ commit+diffstat). SNAPSHOT = Edit direto.
- Tipos: `ativação|descoberta|decisão|tentativa|blocker|unblock|refactor|nota|conclusão` (`[MARCO]` p/ crítica) · Fase: `pendente|em progresso|concluído|bloqueado|importada (origem)|descartado`.
- Lint: SNAPSHOT único no topo; TL;DR fora = erro. Citações LITERAIS (R.15).

## 4. `digest.md` — ≤2.000B, GERADO pela ferramenta

archive E discard exigem; `close` gera (NUNCA conte bytes). Refino: `specctl digest <id> --stdin|--file` (re-validado; LF, HTML descontado).

## 5. `features/<area>.md`

```markdown
# Feature: <nome-kebab-case>

**Keywords:** a, b
**Arquivos principais:**
  - path/a.ts
**Resumo:** 1 frase densa.

## Specs desta feature
### Concluídas
- SPEC-<id> | YYYY-MM-DD | `hash` | Título
### Planejadas (future/)
- SPEC-<id> | Título | Motivo

## Estado atual
Prosa consolidada (single-writer); SPECs APENDAM
### Delta de estado (SPEC-<id>, ts)

## Decisões arquiteturais ativas
- DEC-YYYYMMDD-HHMM-slug [ativa | obsoleta → DEC-x | substituída por SPEC-y] (SPEC-<id>) — decisão + trade-off.

## Alternativas consideradas e rejeitadas
- SPEC-<id> | alternativa — rejeitada em <ts>. Motivo.

## Gotchas
- SPEC-<id> | armadilha (<ts>) — como evitar. (citado por: SPEC-a)
```

- Voo → `docs/claims/` (R.11), sem "Em execução" aqui. Seções compartilhadas: line-oriented (linha inicia por SPEC-/DEC-id), NUNCA reordenar. DEC-id ÚNICO no repo.
- Gotcha repetido: apendar `(citado por: ...)`; ≥3 SPECs → promoção (lifecycle).
- Sem teto: nº de features ilimitado, memória viva cresce livre. `specctl rollup <area>` (MANUAL/opcional) enxuga o auto-load N1 movendo blocos antigos → `<area>.history.md`, nunca deletado. Nada é lintado nem bloqueado por tamanho.

## 6. `docs/claims/SPEC-<id>.md`

specctl gere (activate cria; archive/discard/pause removem); campos SPEC/Título/Owner/Branch/**Base** (branch de origem — o menu de finalização do close usa)/Features/Ativada; vive em MAIN.

## 7. `docs/programs/<slug>.md`

`# Programa: <slug>` + `**Owner:**` + 1 linha/nó `- SPEC-<id> | depende de: —|SPEC-<id2>`. `Bloqueia`/ordem: DERIVADOS, NUNCA escritos. Detalhe: rules/programs.md.

## 8. `docs/TAXONOMY.md`

`- <area> — definição em 1 linha`; namespaces com `/` (back/auth). Toda feature na TAXONOMY (lint); área NOVA = usuário confirma (R.13).

## 9. Artefatos de porte

Só G com pipeline: `prd.md`(+RF-N), `techspec.md`, `tasks.md`/`NN_task.md`, `bugs.md`, `qa|review|bugfix-report.md`, `evidence/`, `intake/`, `tmp/` (R.12). Templates+semântica: **rules/formats-pipeline.md**.

## 10. Importação

Verbatim em `intake/`; `prd.md` normalizado `**Origem:** importado (time X, data, vN)`; fase externa → `importada (time X)`. Fluxo: rules/lifecycle.md.
