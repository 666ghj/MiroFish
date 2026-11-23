# Interop — o harness prd sob governança SDD

> **PARE.** Este arquivo só se aplica se o manifesto tiver `interop` ≠ `none`. Cobre: como o harness prd executa sob governança da v4 (workspace external/inline, importação, adopt-workspace). Fora disso, o brief/--help respondem.

> Leia quando: o manifesto tiver `interop: external|inline`, ao rodar qualquer skill do pipeline prd (cria-prd → executar-bugfix), ao importar artefatos de outro time (`/spec importar`) ou ao fechar SPEC com workspace.

## Papéis: a v4 governa, o harness executa

O harness prd é um executor opcional. Camadas, não paralelismo: a v4 é o anel externo — contrato (main.md), memória entre sessões (journal/features), aceite (R.6.2), ciclo de vida; o pipeline é o miolo de execução dentro do anel. O que NUNCA acontece: o pipeline decidir aceite (R.6.2 é do anel) ou a memória viver no techspec (decisões com efeito além da SPEC sobem para features/ no fechamento). Distribuição (v4.1.1): o init VENDORIZA o pipeline por padrão — `templates/skills/` + `templates/agents/` do harness → `.claude/skills/` e `.claude/agents/` DO PROJETO (repo auto-contido; devs e CI na mesma versão) — e grava `interop` no manifesto (default com pipeline: `inline`). Cópias globais em `~/.claude`, quando existirem, são executor equivalente e fonte de re-sync — nunca dependência.

## Porte decide quando o pipeline entra

Proposto pela IA no checkpoint (sinais: arquivos estimados, features tocadas, nº de critérios), confirmado pelo usuário no mesmo round-trip:

| Porte | Processo | Pipeline |
|---|---|---|
| **P** (pontual) | main.md mínimo (objetivo + 1-3 critérios) + journal | ZERO — minutos até código |
| **M** (médio) | main.md completo (contrato de 1 página = mini-PRD) + `verify:` + fases no SNAPSHOT | não — sem prd/techspec separados |
| **G** (grande) | multi-sessão/multi-área | completo OU parcial (à la carte: só techspec quando a arquitetura é o difícil; só tasks quando contrato+design estão claros) — via harness (este doc) ou standalone (`docs/rules/formats.md`) |

Correção pontual nunca vê pipeline. Escalação legítima no meio: `[decisão] upgrade de porte P→M→G` no journal.

**Porte G ⇒ caminho do pipeline é pergunta EXPLÍCITA no checkpoint** (`completo | só techspec | só tasks | sem pipeline`, com recomendação justificada), confirmada pelo usuário no mesmo round-trip do porte e ANTES da redação do main.md — nunca escolha implícita embutida no contrato. Havendo pipeline, a mesma pergunta colhe o **modo de execução** `autônomo | com gates` (item 5 do preâmbulo, abaixo). Detalhe e critérios de recomendação: rules/lifecycle.md §1.

## 1 feature = 1 SPEC (fases, nunca SPECs por fase)

PRD, techspec, tasks e QA NÃO são SPECs — são FASES de uma única SPEC; o arco inteiro do pipeline é um entregável. O main.md nasce ANTES de tudo (contrato-sumário enxuto, validado no checkpoint); o journal atravessa todas as sessões do arco — a memória que o pipeline não tem sozinho. Exceção: feature gigante vira PROGRAMA (`docs/rules/programs.md`) e os blocos viram SPECs próprias.

## Modos de workspace (manifesto `interop:`)

| Modo | Artefatos vivem em | Campo no main.md |
|---|---|---|
| `none` | pipeline não roda; porte G usa templates nativos | `**Workspace:** —` |
| `external` | `tasks/prd-<slug>/` — o caminho DAS skills, intocado | `**Workspace:** tasks/prd-<slug>/` |
| `inline` | dentro da pasta da SPEC | `**Workspace:** inline` |

Escolha POR PROJETO, gravada no manifesto e injetada pela cápsula a cada prompt (`workspace=<modo>`). O campo Workspace/Porte do main.md é preenchido pelo specctl na ativação.

**Regra anti-conflito do `external`:** skills externas gravam nos caminhos DELAS — NÃO redirecione os outputs. A v4 cede a autoridade de caminho dentro do workspace; em troca ele é declarado, entra no secret-scan e é auditável. As skills criam `evidence/` e `tmp/` no workspace (e garantem gitignore de `tasks/**/tmp/`). No fechamento, `specctl adopt-workspace <id>` COPIA um snapshot dos artefatos para a pasta da SPEC ANTES do archive — o archive fica auto-contido E o workspace original permanece no lugar (um /executar-bugfix futuro depende do caminho original). O workspace NÃO é movido, nunca.

**Regra do `inline` (substituição de caminho ÚNICA):** injetada pela cápsula: "WORKSPACE: `docs/active/SPEC-<id>/` — substitua `./tasks/prd-<slug>/` por este caminho em TODOS os passos, leitura E escrita". A cadeia inteira usa o MESMO caminho substituído, então as validações de pré-requisito das skills permanecem consistentes. Tudo arquiva junto; adopt-workspace é desnecessário.

Descartado por design: árvore paralela `docs/tasks/prd-*/` — muda a convenção das skills E fica fora do ciclo de vida da SPEC.

## O preâmbulo "SDD Interop" nas skills (estado real — aplicado 2026-07-02)

As 8 skills do harness (cria-prd, cria-techspec, criar-tasks, executar-task, task-review, executar-review, executar-qa, executar-bugfix) carregam a seção `## SDD Interop (conditional)` no topo. frontend-design não tem (diretrizes, sem artefatos de workspace). Detecção DUPLA: o preâmbulo só ativa se `docs/.spec-system.json` E `docs/RULES.md` existirem — manifesto órfão não sequestra a skill; sem manifesto, comportamento standalone byte a byte. Quando ativo, faz 7 coisas:

1. **Workspace** — resolve o diretório de trabalho do manifesto/SPEC ativa; toda referência da skill a `./tasks/prd-[slug]/` significa o diretório resolvido (é o que implementa os dois modos acima).
2. **Slug verbatim** — slug/workspace fornecido pelo chamador ou manifesto é usado como está; a skill nunca deriva um segundo identificador para a mesma feature.
3. **main.md equivalente-PRD** — pré-requisito "prd.md existe" aceita o main.md da SPEC como documento de requisitos (destrava o uso à la carte do porte G parcial).
4. **Dedupe de entrevista** — antes de qualquer pergunta de clarificação, a skill lê main.md + journal e pergunta SÓ o que ainda não foi respondido, registrando respostas inferidas com fonte.
5. **Aprovações — governadas pelo modo de execução** do checkpoint, registrado no journal (`autônomo | com gates`; sem registro → `com gates`, fail-safe): em `autônomo`, apresentações de plano/lista viram informativas (registra no journal e prossegue); em `com gates`, a skill PARA para aprovação explícita em 4 pontos — após /cria-prd (RFs), após /cria-techspec (decisões de design), após /criar-tasks (lista de tasks) e ANTES de cada /executar-task. Em AMBOS os modos, decisões que mudam critérios de aceite ou escopo da SPEC SEMPRE exigem aprovação explícita do usuário. No executar-bugfix: implementação autônoma, EXCETO fix que altera critério contratado (1 pergunta por critério afetado) — alinha o "do not wait for approval" com R.6.2.
6. **Commands** — os labels do manifesto (`commands: {test, typecheck, lint, dev, e2e}`) têm precedência sobre qualquer comando hardcoded/detectado.
7. **Retroalimentação (step final obrigatório)** — resumo datado de decisões/desvios/aprendizados apendado ao journal + ponteiros de artefato atualizados no main.md. executar-qa adicionalmente marca critérios cobertos por RF verificado com timestamp + link de evidência; executar-bugfix registra causas raiz como gotchas candidatos das features tocadas.

Degradação graciosa: o preâmbulo só pede operações de arquivo puras — specctl/hooks são conveniência, nunca pré-requisito da skill.

## Mapa fase → skill → artefato → retroalimentação

Artefatos na RAIZ do workspace + `evidence/` (persistente) + `tmp/` (gitignored).

| Fase (SNAPSHOT) | Skill | Artefato | Retroalimentação imediata (feita pela SESSÃO) |
|---|---|---|---|
| Contrato | — (checkpoint + plan mode) | `main.md` enxuto (semente, não quase-PRD) | validação humana = contrato v1 |
| 1. Requisitos | /cria-prd | `prd.md` (RF-N) | ponteiro `**PRD:**` no cabeçalho; critérios ↔ `(cobre RF-n)` — mudança de contrato → validação humana (2º e último gate); respostas → "Respostas-chave" do SNAPSHOT; `[nota]` no LOG |
| 2. Design | /cria-techspec | `techspec.md` | `[decisão]` no LOG (candidatas a DEC-id na feature no fechamento); ponteiro `**TechSpec:**` |
| 3. Breakdown | /criar-tasks | `tasks.md` + `NN_task.md` | ponteiro `**Tasks:**`; SNAPSHOT re-mapeia fases→blocos ("Fase 4 = tasks 3.0-5.0") |
| 4..N. Execução | /executar-task (+ task-review) | código + `tasks.md` marcado (formato R.6) + `NN_task_review.md` | `[tentativa]/[descoberta]` no LOG; SNAPSHOT por marco; trailer `Spec:` (R.17); R.6.1 |
| Review | /executar-review | `review-report.md` | desvio de techspec → `[decisão]` / alternativa rejeitada candidata |
| QA | /executar-qa | `qa-report.md` + `bugs.md` + `evidence/RF-XX-*.png` | RF PASSED → marca critérios `(cobre RF-n)` no main.md com ts + link de evidência; FAILED → bugs.md, critério fica `[ ]` |
| Bugfix | /executar-bugfix | fixes + `bugs.md` atualizado + `bugfix-report.md` | causa raiz → `[descoberta]` + gotcha candidato |
| Fechamento | /spec fechar (v4, nunca skill) | `digest.md` | R.6.2 item a item → gotchas → digest → adopt-workspace (external) → `specctl archive` |

**Três altitudes de progresso, zero sobreposição:** task fecha em `tasks.md`; fase fecha no SNAPSHOT; critério fecha no `main.md`.

**Contrato do bugs.md** (assets/bugs-template.md da skill): append-only — nunca sobrescrever/deletar entradas; IDs contínuos `BUG-NN` entre execuções; Status ∈ `Aberto | Corrigido | Verificado | Reaberto | Não reproduzível`; re-QA re-testa todo `Corrigido` → `Verificado` ou `Reaberto`; cada bug aponta `Requisito afetado: RF-XX` e evidência em `evidence/`; `Correção aplicada`/`Testes de regressão` são preenchidos pelo executar-bugfix.

**Quem atualiza o quê:** ponteiros e fases = a SESSÃO, imediatamente após cada skill (R.6.1 — tempo real, nunca batch no fechamento); Workspace/Porte = specctl na ativação; critérios↔RF = sessão propõe, usuário valida; marcação de critérios = `specctl verify` / pós-QA com evidência. **QA APPROVED não arquiva** — fechamento é decisão humana, sempre.

## Importação de artefatos externos — `/spec importar`

Regra de ouro: **artefato recebido é INSUMO, não contrato** — o main.md continua sendo o contrato local (autoridade R.6.2 local; aceite do time de origem, se necessário, vira critério `| evidence: manual @usuario`).

1. **Ingestão com proveniência:** original preservado como chegou em `intake/` (nunca reescrito) + `prd.md` normalizado ao template com `**Origem:** importado (time X, data, vN)` e RF-N extraídos sob confirmação do usuário. Normalizado, o artefato é consumível pelas skills sem mudanças nelas.
2. **Checkpoint normal** (feature da TAXONOMY + porte).
3. **main.md derivado DO PRD**, critérios `(cobre RF-n)`, validação humana; fase marcada `importada (time X)` no SNAPSHOT.
4. **Checagem de conflito contra a memória viva:** o importado é confrontado com as decisões ativas das features e a CONSTITUTION ANTES do aceite ("PRD assume Redis; DEC-x padronizou SQS — conflito a levar ao time X") — contradições entre times pegas antes do código.
5. **Ciclo retoma na primeira fase FALTANTE:** só PRD → techspec; PRD+techspec → tasks; tudo → execução. Tasks recebidas ficam como referência em `intake/` e NÃO são normalizadas — re-planejar localmente com /criar-tasks usando-as como insumo (quem conhece o código é o time local).

Nova versão do artefato chega → `/spec importar` de novo: diff vN×vN+1 → `[decisão]` no journal → critérios afetados revisados com validação humana.

## A linha que não se cruza

**Um dono de governança, nunca dois.** Ou a v4 orquestra (com ou sem o harness executando o miolo), ou o projeto usa só o harness — nunca dois donos de memória/aceite. Fricções conhecidas do modo misto (aceitas, com backstop):

- fix autônomo tocando critério contratado → TIER-0 re-injetado por prompt + gate de archive (critérios abertos seguram);
- sessão que negligencia retroalimentação → Stop hook + audit warn "artefatos de pipeline sem contrapartida no journal";
- inline: modelo esquecer a substituição no meio da cadeia → a cápsula re-injeta o workspace a cada prompt.
