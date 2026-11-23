# Regras de documentação — SPEC-driven

Este projeto segue um processo RÍGIDO de documentação baseado em specs. Qualquer AI (qualquer modelo) opera dentro dele. Antes de qualquer código, garantir que a estrutura abaixo existe; se faltar algo, corrigir.

## Estrutura de pastas

```
CLAUDE.md                  ← root do projeto. Orientações específicas.
                            LEITURA OBRIGATÓRIA em TODA sessão.
docs/
├── RULES.md               ← este arquivo. Processo de documentação.
├── memory.md              ← ESTADO ATUAL. Lido no início de TODA sessão.
├── history.md             ← log cronológico de specs/sessões
├── vision.md              ← (opcional) visão de produto
├── architecture.md        ← (opcional) arquitetura técnica
├── active/                ← specs em execução
│   ├── SPEC-NNN-titulo.md          ← definição da spec
│   └── SPEC-NNN-titulo-session.md  ← log vivo de execução (obrigatório)
├── future/                ← specs planejadas (só o arquivo SPEC-NNN-titulo.md)
├── archive/               ← specs concluídas (spec + session juntos)
└── discard/               ← specs descartadas, com justificativa
```

## Regras OBRIGATÓRIAS

### 1. Toda sessão começa lendo 2 arquivos

Antes de qualquer código ou ação:

1. `CLAUDE.md` no root — orientações específicas do projeto (stack, convenções, gotchas)
2. `docs/memory.md` — estado atual, specs ativas, próximos passos

Se houver spec ativa em execução, ler também o arquivo de sessão dela (`SPEC-NNN-titulo-session.md`) para retomar de onde parou.

### 2. Toda spec referenciada tem arquivo .md correspondente

Se memory.md, history.md ou outra spec referencia SPEC-NNN, **o arquivo DEVE existir** em `active/`, `archive/` ou `discard/`. Zero referências fantasma.

### 3. Timestamps em tudo — SEMPRE

Toda entrada, decisão, observação, mudança de estado tem **data e hora no formato `YYYY-MM-DD HH:MM`**. Sem exceção:

- Criação, ativação, conclusão, descarte de spec → cabeçalho da spec
- Toda entrada no `session.md` → começa com `## YYYY-MM-DD HH:MM — título`
- Toda linha em `memory.md` "Última atualização" → `YYYY-MM-DD HH:MM`
- Toda linha em `history.md` → data em coluna
- Commits referenciados quando existem (hash curto)

### 4. Toda spec em execução tem arquivo de sessão

Ao ativar (mover de `future/` para `active/`), **criar junto** `SPEC-NNN-titulo-session.md`. Esse arquivo é o **log vivo**: documenta passo-a-passo decisões, descobertas, tentativas que falharam, hipóteses testadas, ajustes de rumo.

A spec principal descreve **o quê + o porquê + critério de aceite** (visão estática).
O session file registra **como foi feito, o que aconteceu durante** (memória viva).

**Atualizar continuamente durante a execução.** Cada entrada é uma seção com timestamp. Nunca sobrescrever entradas antigas — só adicionar. É um log append-only.

A spec principal DEVE referenciar seu session file no cabeçalho via campo `Sessão:`.

### 5. Uma spec por entregável coeso

- Nem gigante (> 3 sessões de trabalho → quebrar em várias)
- Nem minúsculo (< 1h → agrupar com outra)
- Cada spec é auto-suficiente: qualquer AI deve conseguir retomar lendo `CLAUDE.md` + `memory.md` + `SPEC-NNN-*.md` + `SPEC-NNN-*-session.md`

### 6. Specs nunca são deletadas

- Concluída → `archive/` (spec + session juntos)
- Abandonada → `discard/` com seção "Justificativa de descarte"
- Renomear, reescopar ou fundir é permitido; apagar não é

### 7. Execute com disciplina durante a sessão

- **Ao ativar**: move `future/SPEC-NNN-*.md` → `active/`, cria `active/SPEC-NNN-*-session.md` com primeira entrada timestampada, atualiza `memory.md`
- **Durante**: mantém o "Status snapshot" no topo do session sempre atualizado (sobrescreve) + adiciona entradas novas no "Log cronológico" (append-only) + atualiza as seções "Fatos / Inferências / Dúvidas" conforme descobre
- **Ao concluir**: move spec + session → `archive/`, marca `Status: done` + `Concluída: <timestamp>` + `Commit: <hash>` na spec, última entrada do session com fechamento, atualiza `memory.md` e `history.md`

### 8. Isolamento entre sessões — leve mas explícito

Durante trabalho em uma spec X, a AI lê APENAS:

- `CLAUDE.md` (root) — orientações do projeto
- `docs/RULES.md` — este arquivo
- `docs/memory.md` — estado global
- `docs/active/SPEC-X-*.md` — definição da spec ativa
- `docs/active/SPEC-X-*-session.md` — log de execução da spec ativa

**NÃO ler por conta própria**:
- Session files de outras specs (mesmo que também ativas)
- Session files arquivadas em `archive/`
- Specs em `future/` (exceto quando ativando uma nova)
- Session files em `discard/`

Essas leituras requerem **pedido explícito** do usuário (ex.: "consulte o session da SPEC-005", "olha o que foi feito na SPEC-003"). Isso impede que contexto de uma spec contamine decisões de outra.

**`history.md` e `memory.md` podem ser consultados livremente** — são índices agregados, não conteúdo detalhado. Também é permitido identificar **nomes** de arquivos em `archive/` via glob/listagem quando precisar localizar uma spec específica (sem abrir o conteúdo).

### 9. Todo prompt livre deve ser classificado

Qualquer mensagem do usuário em uma sessão (tarefa, pergunta, comando, comentário) deve ser tratada pela AI como pertencendo a UMA destas 3 categorias:

1. **Continuidade de spec ativa** — o prompt é parte/evolução/fix/ajuste de trabalho já em andamento em `docs/active/SPEC-X-*.md`. AI registra no session file da SPEC X como entrada nova no log cronológico e atualiza Status snapshot / Fatos / Dúvidas conforme o caso.

2. **Nova spec** — o prompt representa um entregável novo que ainda não tem spec. AI deve criar `docs/future/SPEC-NNN-*.md` (ou direto em `active/` se vai executar agora) + arquivo de sessão, registrar em `memory.md` e `history.md`, ANTES de começar a trabalhar.

3. **Prompt livre sem registro** — pergunta pontual, exploração, comando de utilidade (ex.: "qual a versão do node?", "me explica o que é X", "lista os arquivos de Y"). NÃO gera trabalho persistido, NÃO cria spec, NÃO mexe em session/memory/history.

#### Regra de desambiguação — OBRIGATÓRIA

Quando a classificação NÃO é imediatamente óbvia, a AI **DEVE perguntar explicitamente** ao usuário antes de começar:

> "Este pedido é: (a) continuação de SPEC-X (ativa), (b) uma SPEC nova que devo criar, ou (c) prompt livre sem registro?"

Não inferir silenciosamente em casos ambíguos. A pergunta mantém o usuário no controle do que está sendo registrado.

#### Sinais orientadores

**Continuidade** (quando há spec ativa e o prompt conecta ao escopo dela):
- "ainda não funciona", "ajusta aquilo", "continua", "não ficou bom"
- resposta a teste/pergunta que a AI fez
- tema diretamente dentro do escopo da spec ativa

**Nova spec** (tema novo OU fora do escopo das ativas):
- "agora quero implementar X", "preciso de uma feature Y"
- entrega nova com critério de aceite claro, > 1h de trabalho
- tema fora do escopo declarado de qualquer spec ativa

**Prompt livre** (não persiste):
- pergunta pontual sobre conceito/estado/comando
- exploração ou investigação sem intenção de alterar código
- utilitário (git status, listar arquivos, checar versão)
- solicitação de explicação ou resumo

#### Default quando há UMA spec ativa e o prompt conecta

Se existe exatamente uma spec em `active/` e o prompt claramente conecta ao escopo dela, classificar como **continuidade** sem perguntar. Se conecta parcialmente ou ambiguamente, PERGUNTAR.

#### Default quando NÃO há spec ativa

Se `active/` está vazio e o prompt parece trabalho real (> 1h, entrega), classificar como **nova spec** e perguntar "Vou criar SPEC-NNN-<titulo-sugerido>, ok?". Se parece pontual, tratar como **prompt livre** sem perguntar.

#### Nunca misturar

Não acumular trabalho de múltiplas specs na mesma sessão de execução. Se o usuário traz tema de outra spec no meio do trabalho em SPEC-X, PERGUNTAR se troca de contexto ou se quer criar spec nova.

## Ciclo de vida de uma spec

```
1. CRIAÇÃO
   Arquivo SPEC-NNN-titulo.md criado em future/ (ou direto em active/
   se vai executar imediatamente). Entry em history.md com timestamp.

2. ATIVAÇÃO
   - Move future/ → active/
   - CRIA arquivo active/SPEC-NNN-titulo-session.md com:
     * Cabeçalho linkando para a spec
     * Primeira entrada "## YYYY-MM-DD HH:MM — ativação" explicando
       contexto e plano inicial
   - memory.md lista spec em "Ativas"
   - Spec ganha campos: `Ativada: YYYY-MM-DD HH:MM`, `Sessão: SPEC-NNN-titulo-session.md`

3. EXECUÇÃO
   Código acontece. A CADA momento significativo, adicionar entrada no session:
   - Nova hipótese sendo testada
   - Descoberta sobre o código/sistema
   - Decisão de arquitetura com trade-off
   - Tentativa que falhou e por quê
   - Ajuste de escopo
   - Blocker encontrado

   Formato de cada entrada:
   ## YYYY-MM-DD HH:MM — [tipo] Título curto

   Corpo: 2-10 linhas descrevendo o que aconteceu, decisão tomada,
   arquivos afetados (com links), links para commits se aplicável.

   Se escopo mudar, atualizar também a seção "Escopo" da spec principal.

4. CONCLUSÃO
   - Move active/SPEC-NNN-*.md + active/SPEC-NNN-*-session.md → archive/
   - Spec: `Status: done`, `Concluída: <timestamp>`, `Commit: <hash>`
   - Session: última entrada "## YYYY-MM-DD HH:MM — conclusão" com
     resumo do entregue
   - memory.md remove de ativas
   - history.md marca DONE + data + commit

5. DESCARTE (se abandonada)
   - Move para discard/ (spec + session)
   - Adicionar no fim da spec seção "Justificativa de descarte"
     com timestamp e motivo
   - history.md marca DISCARDED
```

## Formato obrigatório de uma spec

```markdown
# SPEC-NNN: Título curto

**Status:** draft | active | done | discarded
**Criada:** YYYY-MM-DD HH:MM
**Ativada:** YYYY-MM-DD HH:MM
**Concluída:** YYYY-MM-DD HH:MM
**Commit:** `hash` mensagem curta
**Depende de:** SPEC-NNN (se aplicável)
**Sessão:** [SPEC-NNN-titulo-session.md](./SPEC-NNN-titulo-session.md)

## Objetivo
O que entrega e por quê. 2-3 frases.

## Escopo
DENTRO:
- item 1
- item 2

FORA:
- item excluído 1

## Implementação
Detalhes técnicos: arquivos, decisões-chave, mapeamentos, gotchas.
(Visão estática — o log de como foi descoberto/decidido vai no session file.)

## Critério de aceite
- [ ] checkbox 1
- [ ] checkbox 2
```

## Formato obrigatório do arquivo de sessão

O session file tem 3 regiões com regras diferentes de edição:

1. **Status snapshot** (topo) → **sobrescrever** ao vivo a cada update significativo. É o panorama atual.
2. **Fatos / Inferências / Dúvidas** (meio) → **adicionar + promover/demover**. Fatos promovidos de inferências. Dúvidas resolvidas viram fatos. Tudo timestampado.
3. **Log cronológico** (fim) → **append-only**. Nunca editar entradas antigas.

### Template completo

```markdown
# Sessão de execução — SPEC-NNN: Título

> Spec: [SPEC-NNN-titulo.md](./SPEC-NNN-titulo.md)
> Criada em: YYYY-MM-DD HH:MM

---

## Status snapshot

_(sobrescrever ao vivo — NÃO é append-only)_

### Fases / etapas

| # | Descrição | Status | Progresso | Bloqueios |
|---|-----------|--------|-----------|-----------|
| 1 | Investigar shape do XML | concluído | — | — |
| 2 | Implementar parser | em progresso | 40% (2/5) | — |
| 3 | Integrar no renderer | pendente | 0% | depende de 2 |

Status possíveis: `pendente` | `em progresso` | `concluído` | `bloqueado` | `descartado`.
Coluna "Progresso" obrigatória quando a fase tem >3 sub-itens; omitir (`—`) quando binário.

### Próximos passos

- [ ] item 1
- [ ] item 2

### Bloqueios ativos

_(ou "nenhum")_

---

## Fatos confirmados

Coisas OBSERVADAS no código/sistema/teste. Não especular aqui.
Cada fato com timestamp e fonte (arquivo:linha, comando:saída, URL de resposta).

- [YYYY-MM-DD HH:MM] Fato X. Fonte: `foo.ts:42` / `curl ... → 200`.
- [YYYY-MM-DD HH:MM] Fato Y. Fonte: screenshot compartilhado pelo usuário.

## Inferências prováveis

Hipóteses razoáveis baseadas em fatos, mas AINDA NÃO validadas.
Nunca apresentar como fato. Quando validar, promover para "Fatos".

- [YYYY-MM-DD HH:MM] Provavelmente X, porque Y. Validar rodando Z.

## Dúvidas em aberto

Coisas que ainda não sei e PRECISO confirmar antes de decidir.
Explicitar evita chutar. Resolver = mover para Fatos ou Inferências.

- [YYYY-MM-DD HH:MM] Não sei por que X acontece. Próxima ação: Y.

---

## Log cronológico

_(append-only: nunca editar entradas antigas, só adicionar novas)_

## YYYY-MM-DD HH:MM — ativação

Contexto inicial. Plano. Arquivos identificados como relevantes.

## YYYY-MM-DD HH:MM — [descoberta] Título curto

Tentei A. Resultado B. Promovendo dúvida "Z" para fato/inferência.

Arquivos: [foo.ts:42](../foo.ts#L42)

## YYYY-MM-DD HH:MM — [decisão] Título curto

Considerei X e Y. Escolhi Y porque [trade-off].
Commit: `abc1234`

## YYYY-MM-DD HH:MM — [blocker] Título curto

[descrição do bloqueio]. Atualizando Status snapshot para refletir.

## YYYY-MM-DD HH:MM — [conclusão] resumo final

Entregue: [lista]. Critério de aceite: todos ✓.
Pendências pequenas deixadas para SPEC-NNN+1: [lista].
```

### Por que essa estrutura

- **Status snapshot no topo** — quem abre o arquivo sabe o estado em 10 segundos sem ler log inteiro.
- **Fatos × Inferências × Dúvidas** — força a AI a ser honesta sobre nível de confiança. Evita chutes apresentados como fato.
- **Log cronológico embaixo** — memória profunda de como cheguei até aqui, útil para auditoria e retomada.

### Tipos de entrada no log

Use prefixos em `[colchetes]` no título para facilitar busca visual:
- `[ativação]`, `[descoberta]`, `[decisão]`, `[tentativa]`, `[blocker]`, `[unblock]`, `[conclusão]`, `[refactor]`, `[nota]`

## Formato de `memory.md`

Arquivo curto, sempre carregado no contexto. Até ~100 linhas.

```markdown
# Memory — Estado do projeto

> Toda sessão AI começa lendo CLAUDE.md + este arquivo.
> Última atualização: YYYY-MM-DD HH:MM

## Foco atual
Parágrafo curto descrevendo no que estamos trabalhando AGORA.

## Specs
| # | Descrição | Status | Sessão |
|---|-----------|--------|--------|
| SPEC-001 | ... | DONE | [log](archive/SPEC-001-*-session.md) |
| SPEC-002 | ... | ATIVA | [log](active/SPEC-002-*-session.md) |
| SPEC-003 | ... | PLANEJADA | — |

## Próximo
Qual é a próxima spec a ativar e por quê.

## Referências rápidas
- Comandos para rodar/testar
- Convenções de código principais
- Links para vision.md / architecture.md se existirem
```

## Formato de `history.md`

Log cronológico que cresce indefinidamente. Não é carregado por default; consultado sob demanda.

```markdown
# History — O que já aconteceu

## Specs concluídas
| # | Spec | Sessão | Concluída em | Commit |
|---|------|--------|-------------|--------|
| 001 | [Título](archive/SPEC-001-titulo.md) | [log](archive/SPEC-001-titulo-session.md) | YYYY-MM-DD HH:MM | `abc1234` |

## Specs descartadas
(ou "Nenhuma até o momento")

## Log de sessões (resumos)
| Data | Spec | Resumo |
|------|------|--------|
| YYYY-MM-DD HH:MM | SPEC-001 | Resumo de 1-2 linhas do que rolou |
```

## Numeração de specs

Escolher uma convenção no início do projeto e documentar aqui:

- **Sequencial simples** (001, 002, 003, …) — mais flexível
- **Por fase/área** (001-009 = infra, 010-019 = feature X, …) — exige planejar faixas

Não importa qual escolher, **não reutilizar números** (mesmo de specs descartadas).

## Escalabilidade

- `memory.md` passou de ~100 linhas? Poda: mover specs DONE antigas para history.md, colapsar fases concluídas.
- `history.md` pode crescer sem limite.
- Quando uma fase grande terminar, criar `archive/session-YYYY-MM-DD-fase.md` com narrativo consolidado daquela fase para contexto histórico profundo.
- Session files antigos ficam em archive/ indefinidamente — eles SÃO a memória de como o projeto foi construído.

## Anti-patterns (não fazer)

- ❌ Pular leitura de CLAUDE.md + memory.md — sempre começa por eles
- ❌ Executar spec sem criar session file
- ❌ Deixar spec ativa sem atualizar session file por sessões inteiras
- ❌ **Editar ou deletar entradas antigas do Log cronológico** (append-only). O Status snapshot PODE ser sobrescrito; o log NÃO.
- ❌ **Apresentar hipóteses como fatos** — se não validou, vai em "Inferências" ou "Dúvidas", não em "Fatos"
- ❌ **Deixar "Fatos / Inferências / Dúvidas" desatualizados** — resolver dúvidas é parte do trabalho, não adiar
- ❌ **Ler sessions de outras specs sem pedido explícito** do usuário (regra 8)
- ❌ **Tratar um prompt ambíguo como continuidade sem perguntar** (regra 9) — se não é óbvio a qual spec pertence, perguntar
- ❌ **Começar trabalho novo sem criar spec** quando é claramente entregável — criar SPEC antes de codar
- ❌ **Misturar trabalho de 2 specs na mesma sessão** — cada sessão de execução é de uma spec só
- ❌ Deletar arquivo de spec — sempre arquivar ou descartar
- ❌ Criar spec sem entry em history.md
- ❌ Escrever código grande sem spec ativa (refatorações de >1h precisam de spec)
- ❌ Referenciar SPEC-NNN inexistente
- ❌ Misturar dois entregáveis numa spec só
- ❌ Omitir timestamps em qualquer entrada

## Sua primeira ação neste projeto (AI)

1. Ler `CLAUDE.md` no root — orientações específicas do projeto.
2. Ler `docs/memory.md` — estado atual.
3. Se houver spec em `active/`, ler também seu `SPEC-*-session.md` para retomar contexto.
4. Aguardar instrução do usuário sobre o que trabalhar.

Confirmar que leu este processo antes de qualquer outra ação.
