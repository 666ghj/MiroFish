---
description: Operador do ciclo de vida de SPECs (SDD v4) — abrir, fechar, pausar, retomar, importar, status
argument-hint: [fechar | status | pausar | retomar | importar <artefato> | <demanda de nova SPEC>]
---

# /spec

Argumentos recebidos: `$ARGUMENTS`

Roteie pela PRIMEIRA palavra de `$ARGUMENTS`. Qualquer outra primeira palavra = rota "nova SPEC" (última seção).

## `fechar` — fluxo de fechamento (ler docs/rules/lifecycle.md §5)

O fechamento é UM comando transacional (`close`) precedido dos passos de JULGAMENTO. Nunca escreva digest à mão nem chame `archive` direto.

1. Identifique a SPEC ativa da branch (única pasta em `docs/active/`; se houver mais de uma, pergunte qual).
2. `node scripts/specctl.mjs close <id> --dry` — lista TUDO que falta (não muta nada). Use essa lista como roteiro.
3. **R.6.2 item a item:** para CADA critério `[ ]` que o --dry apontou, pergunte ao usuário: implementar agora / mover para SPEC nova / aceitar gap. Aceite grava `[aceito-incompleto: "<citação literal do usuário>" YYYY-MM-DD HH:MM]`. NUNCA decida sozinho; NUNCA agrupe itens numa pergunta só.
4. Gotchas e decisões candidatos → apresente ao usuário e atualize `docs/features/<area>.md` de TODAS as features tocadas (R.7: linha em Concluídas com SPEC-id). Gotcha citado por ≥3 SPECs → proponha promoção a CONSTITUTION.md/CLAUDE.md.
5. `[conclusão]` no LOG (`specctl log <id> conclusão "..."`) + SNAPSHOT refletindo a conclusão.
6. Se o manifesto tem `"interop": "external"` e a SPEC declara `**Workspace:**`: `node scripts/specctl.mjs adopt-workspace <id>` (docs/rules/interop.md).
7. `node scripts/specctl.mjs close <id>` — roda os `verify:` pendentes + a suíte do projeto 1×, gera o digest, estampa campos, arquiva e imprime o atestado + menu de finalização git (pergunte item a item; nada automático). Se falhar, resolva o que ele listar e repita. O fechamento é decisão humana: QA aprovado NÃO arquiva sozinho.

## `status`

Rode `node scripts/specctl.mjs brief` e apresente o output.

## `pausar` — ler docs/rules/lifecycle.md

1. Confirme com o usuário a SPEC e o motivo.
2. Registre `[nota]` no journal com o estado de retomada (atualize o SNAPSHOT: "Se retomar, ler:").
3. `node scripts/specctl.mjs pause <id> --motivo "<motivo>"`.

## `retomar` — ler docs/rules/lifecycle.md

1. `node scripts/specctl.mjs resume <id>`.
2. Leia o SNAPSHOT do journal (60 primeiras linhas) e siga "Se retomar, ler:" antes de qualquer código.

## `importar <artefato>` — ler docs/rules/interop.md

Artefato recebido é INSUMO, não contrato — o main.md continua sendo o contrato local.

1. Se não existe SPEC para isso, crie primeiro pela rota "nova SPEC" abaixo.
2. Copie o artefato ORIGINAL, sem reescrever, para `intake/` na pasta da SPEC.
3. Normalize ao template (docs/rules/formats.md): gere `prd.md` com RF-N extraídos SOB CONFIRMAÇÃO do usuário e `**Origem:** importado (time X, data, vN)`.
4. Confronte o artefato com as decisões ativas das features e com CONSTITUTION.md — liste conflitos ANTES do aceite (ex.: "PRD assume Redis; DEC-x padronizou SQS").
5. Derive/ajuste o main.md a partir do PRD, critérios com `(cobre RF-n)` — validação humana (mudança de contrato).
6. Marque a fase como `importada (origem)` no SNAPSHOT e retome na primeira fase FALTANTE: só PRD → techspec; PRD+techspec → tasks; tudo → execução. Tasks recebidas ficam em `intake/` como referência (re-planejar localmente).

## Qualquer outra coisa — demanda de NOVA SPEC

Trate `$ARGUMENTS` inteiro como a demanda. Classificação `[nova]` já confirmada — pule a inferência R.9.

1. **Checkpoint único** (uma só rodada de perguntas): feature(s) de `docs/TAXONOMY.md` (área nova = confirmação explícita, R.13) + porte `P|M|G` (proponha por sinais: arquivos estimados, features tocadas, nº de critérios) + owner.
2. Entre em **plan mode** com o draft do `main.md` como o próprio plano (formato em docs/rules/formats.md). A aprovação do plano É a validação humana do contrato.
3. `node scripts/specctl.mjs new <slug> --porte <P|M|G> --owner @<x> --features <a,b>` (+ `--program <p>` se faz parte de um programa — docs/rules/programs.md; `--workspace <w>` se interop — docs/rules/interop.md; `--future` se não vai ativar agora).
4. Preencha o main.md com o conteúdo aprovado e rode `node scripts/specctl.mjs activate <id> [--branch <b>]`.
5. Porte G: proponha o próximo passo do arco (prd/techspec — via pipeline se instalado, senão templates nativos de docs/rules/formats.md).
