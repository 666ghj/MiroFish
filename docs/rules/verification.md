# Verificação — gate, evidência e graders POR PORTE

> Referência sob demanda (R.6.1/R.6.2). Leia antes de marcar critério `[x]`, fechar fase ou abrir PR. Como o critério vira `[x]` depende do PORTE: P carimba (timestamp+commit); M/G roda o `verify:`.

## Porte decide a forma da evidência

| Porte | Como o critério fecha | Evidência | pass^3 | evidence/ |
|---|---|---|---|---|
| **P** | `specctl check <id> <n>` — carimba `(NOW, commit)` | timestamp + commit | não | não |
| **M/G** | `specctl verify <id> --all` — roda o `verify:` do critério | exit 0 do teste-ALVO, GRAVADO pela ferramenta | só G + flaky | relatórios |

**Porte P — leve por design:**
- Critério P NÃO tem `| verify:` (lint recusa) — fecha com `specctl check <id> <n>`, que estampa timestamp + commit atual. `check` RECUSA critério com `verify:` (rota obrigatória: verify).
- O `commands.test` do manifesto roda **1× DENTRO do `close`** — não é passo do agente: a suíte precisa passar para arquivar, mas você não a invoca a cada critério.
- **NÃO crie suíte nem script novo só para dar `verify:` num P** — é ajuste pontual. Se de fato precisa de teste dedicado, o porte virou M: escale (`specctl escalate <id> M`).
- Sem `evidence/`, sem `pass^3`.

**Porte M/G — o critério aponta o alvo:**
- `verify:` aponta o **teste-ALVO** daquele critério (ex.: `<test> auth/login.spec`), **nunca a suíte inteira** — o alvo é o que este critério prova; a suíte completa roda 1× no `close` (label `test` do manifesto).
- `specctl verify <id>` roda os `verify:` dos critérios **pendentes** (na hora do evento — critérios ainda não implementados não são tocados); `--all` re-verifica também os já `[x]`. Sucesso grava `[x] (NOW, commit, verify: exit 0)`. O `close` **NÃO re-executa** critério com evidência **gravada pela ferramenta** — carimbo à mão não ganha isenção (spoofing).
- Relatórios brutos de verificação → `evidence/` (persistente, referenciável do critério); nunca no journal.

## Fonte dos comandos: o manifesto

`docs/.spec-system.json` → `commands: { test, typecheck, lint, dev, e2e }`. Rode SEMPRE pelos labels — PROIBIDO hardcodar `npm run ...`/`bun ...` em critérios, docs ou hooks. Label vazio = capacidade inexistente no projeto.

## Comando inexistente ≠ comando que falhou

- **Label vazio:** a fase sai como `N/A (sem comando)` no relatório — limitação REPORTADA; nunca PASS silencioso, nunca bloqueio.
- **Comando existe e falhou:** PROBLEMA REAL. Pare, corrija, re-rode. PROIBIDO reclassificar falha como limitação ou pular a fase.

## Regra port-safe (OBRIGATÓRIA em todo teste que sobe servidor)

Porta fixa quebra em paralelo/CI (`EADDRINUSE`) e trava o `verify` em timeout mudo. Servidor de teste SEMPRE em **porta efêmera** (`listen(0)`; o teste lê a porta real de `srv.address().port` — nunca hardcode) e SEMPRE **propagando o stderr do processo filho** (`stdio: ['ignore','pipe','inherit']` — senão a falha some).

## Gate em fases (ordem fixa; falha interrompe a sequência)

**Quando roda:** o gate completo + relatório é ritual de **fechamento/PR** (e de fim de fase em G). Durante a execução de M, feche critérios com o `verify:` alvo — não rode o gate inteiro por critério.

| # | Fase | Comando | PASS quando |
|---|---|---|---|
| 1 | Build | build do projeto, se houver (sem label dedicado: declare-o no `verify:` do critério que dele depende) | compila/empacota sem erro |
| 2 | Types | label `typecheck` | zero erros |
| 3 | Lint | label `lint` | zero erros (warns: reportar) |
| 4 | Testes | label `test`; label `e2e` quando o critério cobre fluxo completo | x/y verdes; cobertura reportada se disponível |
| 5 | Secrets | `node scripts/specctl.mjs lint` (secret-scan em docs/) + varrer o diff de código | zero achados (R.15) |
| 6 | Diff review | `git diff --stat` + leitura dos arquivos alterados | sem mudança não intencional, erro engolido ou caso-borda óbvio |

## Relatório (evidência de M/G para R.6.1)

```
RELATÓRIO DE VERIFICAÇÃO — SPEC-<id> — YYYY-MM-DD HH:MM — commit abc1234
Build:   PASS             Types:  PASS
Lint:    PASS (2 warns)   Testes: PASS (41/41, 84%)
E2E:     N/A (sem comando)
Secrets: PASS             Diff:   6 arquivos, revisado
Veredito: PRONTO | NÃO PRONTO
Pendências: 1. ...
```

Persista em `evidence/` (nome determinístico, ex.: `evidence/verify-fase3.md`) e aponte do critério ou do journal. Relatório não persistido NÃO é evidência. Porte P dispensa relatório — o carimbo do `check` basta.

## Graders — critérios não automatizáveis

| Grader | Quando usar | Como o critério registra |
|---|---|---|
| **code** | determinístico: teste, exit code, diff de schema | sufixo `verify:` com o comando |
| **rule** | forma verificável: regex, schema, contagem | sufixo `verify:` com grep/validador |
| **model** | qualidade subjetiva: clareza de texto, UX, tom | subagente avalia por rubrica escrita → relatório em `evidence/`; o critério aponta a evidência — grader model NUNCA fecha critério sozinho |
| **human** | aceite de contrato, julgamento final | sufixo `evidence: manual @usuario`; R.6.2: só o USUÁRIO aceita incompleto |

Prefira sempre o grader mais determinístico que o critério suportar; desça na tabela só quando o de cima não capturar o critério.

## pass@k — verificações flaky (SÓ porte G)

- `pass@1` = passou de primeira · `pass@3` = ≥1 sucesso em 3 · `pass^3` = 3/3 consecutivos.
- **`pass^3` só se aplica a porte G com flakiness OBSERVADA:** rode 3× e exija 3/3 (ou conserte a flakiness). `pass@3` serve a diagnóstico, não a aceite. Em P/M, verificação flaky é bug a corrigir, não a tolerar.
- Intermitência persistente é problema real: registre `[descoberta]` no journal e trate como bug. Não jogue o dado até passar.
- **Critério sobre saída ESTOCÁSTICA/IA** (ex.: desenho por IA produz grafo válido) é o outro uso legítimo: capacidade fecha com `pass@3`; regressão crítica de release exige `pass^3` — as k execuções registradas em `evidence/`. Grader flaky em gate de fechamento é anti-padrão: conserte o grader, nunca role o dado.
