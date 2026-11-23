# Ciclo de vida da SPEC (rules/lifecycle.md)

> Ler em TODA transição de estado: criação, ativação, execução (checkpoint), retomada, fechamento, descarte, pausa, importação. Status: `draft | active | paused | done | discarded`. Coerência pasta↔status (lint): `active/`→active · `future/`→draft ou paused · `archive/`→done · `discard/`→discarded. **NUNCA deletar nem renomear SPEC** — exceção única: remediação de segredo (R.15, ver rules/verification.md).

## Caminho quente (o ciclo inteiro em ~20 linhas)

O ciclo comum de uma SPEC, com os comandos EXATOS. Detalhe e casos raros: seções abaixo.

**Abrir** — em branch de feature (`main` só aceita `--future`):
```
node scripts/specctl.mjs new <slug> --porte P|M|G --owner @voce --features area
node scripts/specctl.mjs activate <id> --branch feature/<slug>
```

**Trabalhar** — na hora do evento, nunca em batch:
- Critério de porte **P** entregue → `node scripts/specctl.mjs check <id> <n>` (carimba timestamp+commit; recusa critério com `verify:`).
- Critério **M/G** com `verify:` → `node scripts/specctl.mjs verify <id> --all` (roda o teste, grava `[x]` com evidência).
- Decisão/descoberta/tentativa/blocker → `node scripts/specctl.mjs log <id> <tipo> "título"` (append no LOG; a ferramenta anexa commit+diffstat).
- Marco/mudança de fase → sobrescreva o SNAPSHOT (Edit direto).

**Fechar** — decisão humana; R.6.2 item a item:
```
node scripts/specctl.mjs close <id> --dry   # lista o que falta; não muta nada
node scripts/specctl.mjs close <id>          # stage → valida TUDO → move p/ archive/
```
`digest` roda AUTOMÁTICO dentro do `close` — **nunca conte bytes à mão**. `check`/`verify` ao atingir n/n já apontam `close --dry`. (Features não têm gestão de tamanho; `rollup` é manual/opcional.)

### Finalização git — o MODELO pergunta e executa (specctl NUNCA faz merge/push/delete sozinho)

O `close` arquiva a SPEC e imprime o menu de finalização (branch atual + `base` detectada — a branch de onde a feature saiu, gravada no claim na ativação). Ações outward-facing/irreversíveis: **pergunte antes de cada uma, item a item**, e só então rode o git. NÃO automatize.

1. **Commitar** (`git add -A && git commit` com o trailer `Spec: SPEC-<id>`); depois pergunte a via de integração: **(a) merge direto na base** (`git checkout <base> && git merge --no-ff <branch>`) **OU (b) push + PR** (`git push -u origin <branch>` e abrir o PR para `<base>` — o docs-gate roda no PR). A escolha é do usuário; na dúvida, PR.
2. **Voltar para a base?** — pergunte se faz `git checkout <base> && git pull` para trazer o estado corrente do repo.
3. **Deletar a branch de trabalho?** — pergunte antes de `git branch -d <branch>` (e `git push origin --delete <branch>` se remota). Só após o merge/PR estar resolvido.

Invariante dura: **todo trabalho vive em branch própria** — SPEC ativa é proibida em branch protegida (`protected_branches` do manifesto, default `main/master/develop/homolog/hmg`); `new`/`activate`/`resume` e o guard-write bloqueiam. Ajuste a lista no manifesto por projeto (ex.: `trunk`).

## Casos raros

Detalhe situacional abaixo — o caminho quente cobre o comum. Desça aqui só para: descoberta do próximo trabalho, pausar/retomar (`pause`/`resume`), descartar (`discard`), escalonar ou rebaixar porte (`escalate` one-way · `deescalate --cita`), importar artefato, ou reconciliar recovery (edge).

---

## 0. Descoberta — o que pegar a seguir (`docs/active/` vazio)

Quando não há SPEC ativa e o pedido é "siga"/"próximo", a ordem de leitura é o **brief do SessionStart** (já injeta o resumo) → `node scripts/specctl.mjs next` para o detalhe. Três fontes, resolvidas nesta prioridade, SEM vasculhar pastas:

1. **Programas** (ordem = dependências): nós **▶ prontos** (deps todas `done`) do grafo — ver `rules/programs.md` e `docs/PROGRAMS.md` (gerado). Ordem é computada, não escolhida.
2. **Roadmap** (ordem = priorização humana): `docs/ROADMAP.md` — lista **single-writer** (PR dedicado) das SPECs future SEM programa, na ordem desejada de execução. `next` mostra o topo ainda-não-iniciado. SPECs de programa NÃO entram aqui (a ordem delas vem do grafo). Stub criado no init; NÃO é gerado.
3. **Backlog não-priorizado**: future/ `draft` sem programa e fora do roadmap. O sistema **lista** (visibilidade) mas **NUNCA inventa ordem** — priorizar é decisão humana. A IA propõe a mais relevante ao contexto e PERGUNTA, ou você adiciona ao ROADMAP.

Princípio: o v4 **computa** ordem onde ela é estrutural (dependências de programa), **torna visível** o resto, e **nunca fabrica prioridade** entre itens independentes.

## 1. Criação

1. Prompt classificado `[nova]` (R.9) ou `/spec <demanda>` (classificação já confirmada).
2. **Checkpoint ÚNICO** (1 round-trip, via AskUserQuestion): feature(s) da TAXONOMY (área existente = vincula automático; área NOVA = confirmação obrigatória do usuário — R.13) + Porte + Owner.
3. **Porte — o dial de intensidade de processo**, proposto pela IA (sinais: nº de arquivos estimado, features tocadas, nº de critérios) e confirmado no mesmo round-trip:
   - **P (pontual):** bugfix/ajuste → `main.md` mínimo (objetivo + 1-3 critérios) + `journal.md`. ZERO pipeline; minutos até código.
   - **M (médio):** feature pequena → `main.md` completo (o contrato de 1 página é o mini-PRD) + `verify:` nos critérios + checklist de fases no SNAPSHOT. Sem prd/techspec separados.
   - **G (grande):** multi-sessão/multi-área → pipeline completo OU parcial (à la carte: só `techspec.md` quando a arquitetura é o difícil; só `tasks.md` quando contrato+design estão claros), standalone (templates de rules/formats.md §9) ou via harness externo (rules/interop.md).
   - **Porte G ⇒ o CAMINHO do pipeline é pergunta EXPLÍCITA, nunca default silencioso.** No MESMO round-trip do checkpoint, a IA apresenta `completo | só techspec | só tasks | sem pipeline` com recomendação justificada (feature de produto com UI/QA → completo; arquitetura é o difícil → só techspec; contrato+design claros → só tasks) e o usuário confirma ANTES da redação do `main.md` — a densidade do main depende do caminho (completo → main-semente, requisitos finos vão ao prd.md; parcial/sem pipeline → main rico, ele É o documento de requisitos). **Havendo pipeline, a MESMA pergunta colhe o modo de execução:** `autônomo` (fases prosseguem com registro no journal) | `com gates` (aprovação explícita após /cria-prd, após /cria-techspec, após /criar-tasks e ANTES de cada /executar-task). Sem modo registrado no journal → `com gates` (fail-safe); mudável no meio por `[decisão]`. Escolhas registradas na entrada `[ativação]` (ou `[decisão]`) do journal; embuti-las no main.md sem pergunta = violação do checkpoint.
   - Escalação legítima no meio: registrar `[decisão] upgrade de porte P→M` (ou M→G) no journal. Correção pontual NUNCA vê pipeline.
4. **Plan mode com o draft do `main.md` como o próprio plano** — a aprovação do plano É a validação humana do contrato.
5. `specctl new <slug> [--future] [--porte P|M|G] [--owner @x] [--features a,b] [--program p] [--workspace w]` — cria a pasta (active/ ou future/) com ID timestamp REAL e campos preenchidos. `--future` = nasce `draft` em future/ com só `main.md`. Em **branch protegida** (`protected_branches`: default `main/master/develop/homolog/hmg`) só `--future` é permitido (R.2): SPEC ativa exige branch de feature — crie/mude de branch antes do `new` ativo. O `new`/`activate` gravam a **base** (branch de origem) no claim, para o menu de finalização do `close`.

## 2. Ativação

`specctl activate <id> [--branch b]`: move future/→active/; `Status: active`; preenche `Ativada:`; **cria `docs/claims/SPEC-<id>.md`** (commitado em MAIN — visibilidade in-flight, R.11); entrada `[ativação]` no LOG com o plano inicial e arquivos relevantes. Antes de ativar, checar colisão de claims (o brief lista): mesma feature em claim de outro owner → conversar antes de duplicar trabalho.

## 3. Execução — persistência por CHECKPOINT/marco, não "fim de sessão"

"Fim de sessão" é indecidível sob auto-compact. O ritmo de persistência é por checkpoint:

- A cada `[MARCO]`/mudança de fase → **sobrescrever o SNAPSHOT** (Última atualização, Onde tô, Próximo passo, tabela de Fases).
- **Na hora do evento, nunca em batch:** decisão→`[decisão]`, fato+fonte→`[descoberta]`, tentativa+resultado→`[tentativa]`, bloqueio→`[blocker]`/`[unblock]`.
- **R.6.1:** critério validado = marcado no `main.md` na MESMA sessão/lote (via `specctl verify` quando tem `verify:` — só ele grava `[x]` com evidência). Sem commit ainda → `commit —` e preencher antes do fechamento. Parcial → NÃO marca; evidência parcial vai ao journal.
- **R.17:** todo commit sob SPEC ativa leva trailer `Spec: SPEC-<id>`.
- **Retroalimentação:** todo artefato de trabalho gerado na SPEC (review, QA, bugfix — de QUALQUER ferramenta) DEVE ter contrapartida no journal (`[nota]/[decisão]/[descoberta]`) e candidatos a gotcha/decisão acumulados para o fechamento. `specctl audit` avisa artefato sem contrapartida.
- Hooks seguram o resto: PreCompact força flush do SNAPSHOT; Stop bloqueia (1 vez) sessão que editou código sem tocar o journal.

## 3.1 Contrato que muda de rumo (amend) — mudar ≠ deferir

R.6.2 cobre *reduzir/adiar*; esta seção cobre *mudar*: requisito virou outro no meio da execução.

- Critério `[ ]` e Escopo podem ser ALTERADOS — mas a alteração é **mudança de contrato**: exige validação humana explícita (a mesma do plan mode) + `[decisão]` no journal com **antes → depois** e a citação do usuário.
- Critério `[x]` é IMUTÁVEL (evidência estampada não se reescreve). Se o requisito mudou depois de entregue: novo critério para o novo comportamento; o antigo permanece como histórico.
- Mudança que dobra o tamanho do trabalho = sinal de `escalate` (ou de SPEC nova — pergunte).

## 3.2 Blocker que revela dependência faltante

Descobriu no meio que precisa de algo não construído: (1) `specctl log <id> blocker "..."`; (2) crie a dependência como SPEC future (`new <slug> --future`); (3) se a relação é estrutural, registre no programa (`docs/programs/<slug>.md` — PR dedicado); (4) decida com o usuário: `pause` desta SPEC até a dependência, ou seguir em paralelo no que não depende. `[unblock]` quando resolver.

## 3.3 Emergência (hotfix de produção)

A via expressa JÁ É o porte P: `new` + `activate` + código + `check` + `close` cabem em minutos. Se a urgência não permitiu nem isso (push direto sem SPEC): **regularize a posteriori** — crie a SPEC retroativa no primeiro momento calmo, com `[nota] regularização: hotfix aplicado em <commit> antes da SPEC` no journal e critérios refletindo o que foi feito. Bypass sem regularização é dívida invisível — o audit aponta commits sem trailer (R.17).

## 4. Retomada — reconciliação SNAPSHOT × git

Ao retomar (`[continuidade]`, `resume`, ou pós-compact): comparar `**Última atualização:**` do SNAPSHOT com `git log -1` da branch. Se o repo andou DEPOIS do journal → o SNAPSHOT é SUSPEITO: reconstruir o estado a partir do LOG + diff do git e registrar `[nota] recovery` descrevendo o que foi reconciliado. Staleness é sempre por CONTEÚDO, nunca por mtime.

### Convenção de processo acordada em sessão DEVE virar rule no repo

Se o usuário aprovar uma convenção de processo nova (forma de fatiar trabalho, formato de seção, política de fechamento...), ela **DEVE ser proposta como edição de rule/CONSTITUTION no repo NA MESMA sessão** — memória do agente NÃO é fonte normativa (não é auditável, não sobrevive a troca de agente/máquina, e a ferramenta é cega a ela). Antes de propor conceito novo, verifique se o harness já cobre com mecanismo existente (ex.: "fatias de um épico" = programa, ver rules/programs.md) — conceito redundante gera ambiguidade e cegueira de tooling. Premissa 3 do RULES.md: regra sem mecanismo é bug.

### Artefatos do harness NÃO são trabalho de SPEC

`scripts/specctl.mjs`, `docs/rules/*`, os templates gerados (`CLAUDE.md`/`AGENTS.md`) e o `.github/workflows/docs-gate.yml` são **ferramenta vendorizada, pinada em `template_revision`** — o "o que é" da versão instalada, não o "o que mudou". Um diff neles **não é trabalho de SPEC**: classifica-se `[livre]`, é `chore(spec-system)`, e vive fora do ciclo de vida (sem contrato, sem critério de aceite a "completar"). Um agente de continuidade que encontra um diff de harness **não deve investigá-lo como trabalho inacabado** — é um bump de ferramenta. Regra operacional: atualização de harness entra por **um commit atômico** (idealmente branch → PR, como qualquer mudança), **nunca como edições soltas na `main`/protegida**. A evolução do harness acontece na skill global; o projeto só consome a versão.

## 5. Fechamento — decisão HUMANA (QA aprovado NÃO arquiva sozinho)

**O fluxo é UM comando:** `close <id> --dry` lista o que falta → você resolve → `close <id>` valida TUDO e aplica. `archive` é o motor interno do close — não o chame direto no fluxo normal.

**Antes do close — os passos de JULGAMENTO (humano/modelo, o close não decide por você):**

1. **R.6.2 item a item** — texto integral em §5.1. Cada critério `[ ]`: perguntar ao usuário (implementar agora / SPEC nova / aceitar gap). Aceite → marcador `[aceito-incompleto: "<citação literal>" YYYY-MM-DD HH:MM]` — a ÚNICA forma lintável de arquivar com `[ ]`.
2. **Gotchas/decisões candidatos EM LOTE:** apresentar ao usuário o que o journal acumulou; aprovados → `features/<area>.md`. Gotcha repetido: apendar em `(citado por: ...)`, nunca duplicar. Citado por **≥3 SPECs** → PROPOR promoção a `CONSTITUTION.md`/`CLAUDE.md` com confirmação; anotar `(promovido: ..., YYYY-MM-DD)`.
3. **R.7 — features tocadas:** linha em Concluídas (com SPEC-id), `### Delta de estado` se houve mudança arquitetural real, DEC- novas, obsoletar substituídas. O close valida por CONTEÚDO (SPEC-id em Concluídas fora de code fence).
4. **LOG:** entrada `[conclusão]` via `specctl log <id> conclusão "..."` (resumo, critérios, commit) + SNAPSHOT refletindo a conclusão.
5. Se `interop: external` + `Workspace:`: `specctl adopt-workspace <id>` (snapshot dos artefatos externos para a pasta da SPEC).

**O close faz o resto AUTOMÁTICO — não execute à mão:** roda os `verify:` pendentes; roda a suíte do projeto 1× (label `test` do manifesto — falha ABORTA sem mover nada; label vazio = N/A reportado); gera o `digest.md` (nunca conte bytes); estampa `Status: done`/`Concluída:`/`Commit final:`; move para archive/, remove o claim, regenera índices; imprime o atestado + menu de finalização git (ver "Finalização git" acima).

### 5.1 R.6.2 — Escopo da SPEC é CONTRATO; só o usuário pode aceitar incompleto

**Regra-mãe (vale em QUALQUER momento, não só no fechamento):** toda forma de "deixar para depois" — **deferir, adiar, aceitar incompleto, mover para SPEC/fatia futura, reduzir escopo** — exige **AUTORIZAÇÃO EXPLÍCITA do usuário**, registrada como **citação literal**. A IA NUNCA defere/adia por iniciativa própria: PERGUNTA e grava a citação (o marcador é o comprovante). **Sem citação do usuário não há deferral — o item continua no escopo, `[ ]`.** Isso vale durante a execução (mover algo em-escopo para "depois") tanto quanto no fechamento.

**Operação autônoma (agente sem humano no loop):** se o prompt que disparou o trabalho delega decisões EXPLICITAMENTE (ex.: "considere confirmado com a escolha mais razoável e registre"), essa delegação É a autorização — grave o trecho literal do prompt como citação no marcador/journal. Sem delegação explícita no prompt, o R.6.2 vale integral: o item fica `[ ]` e a SPEC fica aberta aguardando o usuário.

**PROIBIDO (formas da mesma violação):**
- Arquivar SPEC com critérios não marcados sem aprovação **explícita** do usuário para cada item não atendido.
- Marcar critério parcial como `[x]` com nota "_parcial_" / "_gap documentado_" / "_X usado em vez de Y_" / "_recomendado para SPEC futura_". Critério é **binário** — ou foi entregue (`[x]`) ou não foi (`[ ]`).
- Listar gaps em "gotchas" das features como se fosse comportamento esperado, antes de o usuário aprovar.
- Apresentar fechamento de SPEC como se estivesse completa quando há critérios `[ ]`.
- Racionalizar escopo reduzido em qualquer fraseado ("aceitar para validação manual", "suficiente para o MVP", "decisão consciente de pragmatismo").

**OBRIGATÓRIO ao chegar no fechamento da SPEC:**

1. **Listar explicitamente** para o usuário **cada critério não marcado** + motivo técnico.
2. Para cada critério não atendido, **perguntar** ao usuário (via `AskUserQuestion` ou texto direto) qual é a decisão:
   - **(a) Implementar agora** — IA volta e completa.
   - **(b) Mover para SPEC nova** — IA propõe escopo da SPEC nova; usuário confirma.
   - **(c) Aceitar como gap permanente** — usuário confirma explicitamente; IA documenta nos gotchas COM referência ao OK do usuário.
3. **Aguardar resposta para CADA item antes de arquivar.**
4. Se usuário escolheu (a) para algum item → SPEC permanece em `active/` até implementação real.
5. Se usuário escolheu (b) ou (c) → IA registra a decisão no `journal.md` como entrada `[decisão]` citando a resposta literal do usuário.

**Motivação:** o `main.md` é o **contrato humano-validado** (rules/formats.md §1). Se a IA pode silenciosamente reduzir o que entrega, o contrato vira aspiracional, não vinculante.

**Aplicação imediata:** se IA já cometeu essa violação (arquivou SPEC com critérios pendentes que ela mesma decidiu deferir), **DEVE** ao ser apontado: (1) reabrir a SPEC — `node scripts/specctl.mjs reopen <id> --motivo "..."` (archive→active, recria claim, registra `[nota]` auditável; NUNCA mover pastas à mão), (2) implementar os itens, (3) re-arquivar com critérios marcados de verdade. Não é "tarde demais" — é correção obrigatória.

**Visibilidade dos deferidos:** todo `[aceito-incompleto]` do repositório aparece em **`docs/DEFERRED.md`** (GERADO pelo `index` — inclusive de SPECs arquivadas, sem abrir o archive) e o brief mostra a contagem. Retomar um item = SPEC nova citando a origem; fechamento indevido = `reopen`.

### 5.2 Enforcement v4 de R.6.2

- Decisão (b) ou (c) → marcador `[aceito-incompleto: "<citação literal do usuário>" YYYY-MM-DD HH:MM]` no próprio critério. Sem o marcador, `specctl archive` e o docs-gate **BLOQUEIAM** archive com `[ ]` — a regra deixou de ser só instrução.
- `specctl verify` é a ponte critério→teste executável: `[x]` nasce de evidência de máquina (exit 0 + commit), não de discurso.

## 5.3 Rollback pós-merge (feature revertida no git)

`git revert` de trabalho já arquivado NÃO reabre a SPEC (o trabalho FOI entregue; a reversão é evento novo):

1. Reverter = **SPEC nova** `[nova]` citando a origem ("reverte SPEC-x — motivo").
2. Na `features/<area>.md`: `### Delta de estado (SPEC-nova, ts)` registrando a reversão; DEC- que caíram → marcar `obsoleta → <motivo/SPEC-nova>`; a linha em Concluídas da SPEC original FICA (histórico verdadeiro).
3. Archive e digest da SPEC original ficam INTACTOS (R.5) — `reopen` é só para fechamento indevido (R.6.2), não para reversão.

## 5.4 Close interrompido no meio (recovery)

O `close` valida tudo ANTES de mutar, e o move para archive/ é o último ato — interrupção deixa no máximo estado pré-move (campos estampados, digest gerado). **Re-rodar `close <id>` é seguro** (idempotente: SPEC já em archive/ = no-op; pendência nova = lista e para). Se o move foi parcial (raro: crash no meio do rename), `specctl lint` acusa a incoerência pasta↔status — corrija movendo a pasta para o destino que o Status indica e rode `specctl index`.

## 6. Descarte

`specctl discard <id> --motivo "..."` exige, ANTES de mover:

1. `main.md`: `Status: discarded` + seção `## Justificativa de descarte` (timestamp; por que não faz mais sentido; o que foi aprendido; permanente ou temporário) — o comando escreve a partir do `--motivo`.
2. **Lições promovidas:** gotchas/decisões que sobrevivem à SPEC → features ANTES do move (descarte preserva aprendizado — é por isso que discard/ existe).
3. `digest.md` GERADO AUTOMÁTICO pelo comando (paridade com o close — nunca conte bytes); lições extras → refine depois via `specctl digest <id> --stdin`.
4. LOG: `[conclusão]` com o motivo (o comando registra).
5. R.7 NÃO se aplica (nada entra em Concluídas). Feature criada junto que não produziu código → removida no mesmo PR.

Move para discard/; remove o claim. NUNCA deletar a pasta.

## 7. Pausa e retomada

- `specctl pause <id> --motivo "..."`: active/→future/; `Status: paused`; `**Pausada em:** YYYY-MM-DD HH:MM — motivo`; remove o claim; PRESERVA `main.md` + `journal.md`.
- `specctl resume <id>`: future/→active/; adiciona `**Reativada em:** YYYY-MM-DD HH:MM`; recria o claim; a primeira entrada nova do LOG cita a pausa para contexto; aplicar a reconciliação do §4.
- Em `future/`: SPEC nunca ativada = só `main.md` (`draft`); SPEC pausada = `main.md` + `journal.md` (`paused`). O lint valida os dois casos.

## 8. Importação — `/spec importar <artefato>`

Regra de ouro: **artefato recebido é INSUMO, não contrato.** O contrato local é o `main.md` (a autoridade do R.6.2 permanece local; aceite do time de origem, se necessário, vira critério `| evidence: manual @pessoa`).

1. **Ingestão com proveniência:** o original vai VERBATIM para `intake/` (nunca reescrito).
2. **Normalização SOB CONFIRMAÇÃO:** gerar `prd.md` no template nativo (rules/formats.md §9) com `**Origem:** importado (time X, YYYY-MM-DD, vN)` e RF-N extraídos — o usuário confirma a extração antes de ela valer.
3. Checkpoint normal (§1): feature + porte + owner.
4. `main.md` derivado DO `prd.md`: critérios com `(cobre RF-n)`, validação humana em plan mode. No SNAPSHOT, a fase entregue de fora recebe status `importada (time X)`.
5. **Checagem de conflito vs memória viva:** confrontar o importado com as DEC- ativas das features e com a CONSTITUTION ANTES do aceite. Conflito → reportar ("PRD assume Redis; DEC-x padronizou SQS — levar ao time X") e registrar `[decisão]` com o desfecho.
6. **Retomar na primeira fase FALTANTE:** só PRD → techspec; PRD+techspec → tasks; tudo → execução. Tasks recebidas ficam como referência em `intake/`, NÃO são normalizadas — re-planejar localmente usando-as como insumo (quem conhece o código é o time local).
7. **Re-importação (nova versão vN+1):** novo arquivo versionado em `intake/` (ex.: `intake/prd-v2.md`); diff vN×vN+1 → `[decisão]` no journal; critérios afetados revisados COM validação humana.
