# CLAUDE.md — {{PROJECT_NAME}}

{{PROJECT_DESC}}

## Primeira coisa: ler dois arquivos — OBRIGATÓRIO

Antes de qualquer código, ler na ordem:

1. [docs/RULES.md](docs/RULES.md) — processo de documentação SPEC-driven completo (estrutura de pastas, ciclo de vida de specs, formato, timestamps, session files). **Fonte da verdade sobre COMO documentar.**
2. [docs/memory.md](docs/memory.md) — estado atual do projeto, foco, specs ativas, próximos passos.

Se houver spec em `docs/active/`, ler também o session file dela (`SPEC-NNN-*-session.md`) para retomar contexto da execução em andamento.

## Stack

**{{STACK}}**

## Comandos

{{DEV_COMMANDS}}

## Processo de specs — resumo

Fonte da verdade: [docs/RULES.md](docs/RULES.md). Resumo:

1. Toda sessão começa lendo CLAUDE.md + docs/memory.md
2. Specs seguem ciclo: `future/` → `active/` → `archive/` (ou `discard/`)
3. Toda spec ativa tem `SPEC-NNN-*-session.md` com 3 regiões:
   - **Status snapshot** (topo, sobrescrever ao vivo) — fases, progresso, bloqueios
   - **Fatos / Inferências / Dúvidas** (meio) — força honestidade sobre confiança
   - **Log cronológico** (fim, append-only) — decisões timestampadas
4. Timestamps `YYYY-MM-DD HH:MM` em TUDO
5. Uma spec por entregável coeso (nem gigante, nem mínimo)
6. Specs nunca são deletadas — arquivadas ou descartadas
7. **Isolamento leve**: durante spec X, ler só CLAUDE.md + RULES.md + memory.md + spec X + session X. Outras sessions só com pedido explícito.
8. **Classificação obrigatória de prompt**: todo prompt do usuário é (a) continuidade de spec ativa, (b) nova spec a criar, ou (c) prompt livre sem registro. Quando ambíguo, **PERGUNTAR antes de começar**. Nunca misturar trabalho de 2 specs.

**Numeração de specs:** {{NUMBERING}}

## Convenções de código

_(adicionar convenções específicas do projeto aqui conforme forem sendo estabelecidas:
tamanho máximo de arquivo, estilo, imports, nomenclatura, comentários, testes, etc.)_

## Arquitetura

_(resumo rápido da arquitetura. Se crescer, mover para `docs/architecture.md` e linkar.)_

## Visão de produto

_(resumo da visão. Se crescer, mover para `docs/vision.md` e linkar.)_
