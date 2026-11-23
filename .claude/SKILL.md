---
name: spec-system-init
description: Initialize the SPEC-driven documentation system in a workspace. Creates docs/ folder (RULES.md, memory.md, history.md, active/, future/, archive/, discard/) and creates or updates CLAUDE.md at project root to point Claude at the rules. Use when the user says "inicializar sistema de documentação", "setup specs", "init doc system", "bootstrap docs", or is starting a new project that needs disciplined spec-based documentation.
---

# spec-system-init

Initialize the SPEC-driven documentation pattern in the current workspace.

## When to trigger

User intent signals:
- "inicialize/inicializar o sistema de documentação"
- "setup/bootstrap specs"
- "init doc system"
- "criar a estrutura de documentação"
- "começar novo projeto com specs"

## What you will create

```
<workspace-root>/
├── CLAUDE.md                 ← created or merged (orientações AI)
└── docs/
    ├── RULES.md              ← processo SPEC-driven completo
    ├── memory.md             ← estado atual, template vazio
    ├── history.md            ← log cronológico, template vazio
    ├── active/               ← vazia
    ├── future/               ← vazia
    ├── archive/              ← vazia
    └── discard/              ← vazia
```

## Execution

### Step 1 — Inspect current state

Use Bash `ls` and Read (with try-catch) to detect:
- `docs/` already exists? → **STOP**. Ask user: "Já existe `docs/`. Abortar (A) ou continuar mesclando (M)?" Default: abortar.
- `CLAUDE.md` at root exists? → flag for MERGE (append-section), not overwrite.
- Current working directory — that is the target workspace root.

### Step 2 — Auto-analyze project (NÃO pergunte o que já está documentado)

ANTES de fazer qualquer pergunta, ler o que já existe no workspace para inferir valores dos placeholders. O usuário não deve redigitar o que já está documentado.

**Fontes de inferência (tentar nesta ordem, parar ao achar):**

**Nome do projeto (`{{PROJECT_NAME}}`):**
1. `CLAUDE.md` → primeiro heading `# CLAUDE.md — <NAME>` ou `# <NAME>`
2. `README.md` / `readme.md` → primeiro `# heading`
3. `package.json` → `"name"` (se monorepo, usar nome root ou pedir confirmação)
4. `pyproject.toml` → `[project] name` ou `[tool.poetry] name`
5. `Cargo.toml` → `[package] name`
6. `go.mod` → `module <name>` (última parte após `/`)
7. `composer.json` → `"name"`
8. `Gemfile` / `*.gemspec` → padrão específico
9. Fallback: nome da pasta-raiz (basename do cwd)

**Descrição (`{{PROJECT_DESC}}`):**
1. `CLAUDE.md` → primeiro parágrafo após o heading
2. `README.md` → primeiro parágrafo após o heading (pulando badges)
3. `package.json` → `"description"`
4. `pyproject.toml` → `description`
5. `Cargo.toml` → `description`
6. Fallback: `"_(adicionar descrição)_"`

**Stack (`{{STACK}}`):**
Combinar múltiplas fontes:
1. `package.json` → detectar `"type": "module"`, deps principais (react, vue, svelte, next, nuxt, astro, express, fastify, nest, hono, elysia), devDeps (typescript, vite, webpack). Formar string tipo "Node.js + TypeScript + React + Vite"
2. `pyproject.toml` / `requirements.txt` → Python + frameworks (fastapi, flask, django, pydantic)
3. `Cargo.toml` → Rust + frameworks (axum, actix, rocket, tokio)
4. `go.mod` → Go + libs (gin, echo, fiber)
5. `*.csproj` / `*.sln` → .NET
6. `pom.xml` / `build.gradle` → Java/Kotlin + Spring/etc.
7. `Gemfile` → Ruby + Rails/etc.
8. `Dockerfile` / `docker-compose.yml` → adicionar "Docker"
9. Bancos detectáveis em `.env.example`, `docker-compose.yml`, deps (`mysql2`, `pg`, `mongodb`, `mssql`, `@prisma/client`, `typeorm`)
10. Fallback: analisar extensões de arquivo mais frequentes no projeto

**Comandos (`{{DEV_COMMANDS}}`):**
1. `package.json` → `"scripts"`. Selecionar os relevantes: `install`/`ci`, `dev`/`start`, `build`, `test`, `lint`. Se tiver workspaces (monorepo), mencionar comando raiz.
2. `Makefile` → targets comuns (`install`, `dev`, `test`, `build`, `run`)
3. `pyproject.toml` → `[tool.poetry.scripts]` ou comandos comuns (`poetry install`, `poetry run <app>`)
4. `README.md` → seção "Installation" / "Getting started" / "Running" / "Usage" — extrair blocos ` ```bash / ```sh / ```shell `
5. `CLAUDE.md` → se tiver seção "Comandos" / "Commands", copiar
6. Fallback: bloco placeholder ` ```bash\n# (adicionar comandos)\n``` `

**Numeração (`{{NUMBERING}}`):**
Não tem fonte óbvia. Default: `"sequential (001, 002, 003, …)"`.

### Step 3 — Apresentar valores detectados e pedir confirmação

Mostrar ao usuário **em UMA mensagem** os valores pré-preenchidos com as fontes de onde vieram, e pedir para confirmar ou editar:

```
Detectei os seguintes valores no workspace:

📦 Nome: <valor>                    (fonte: <arquivo>)
📝 Descrição: <valor>               (fonte: <arquivo>)
🛠️  Stack: <valor>                   (fonte: <arquivo(s)>)
⚡ Comandos:
<bloco>
                                    (fonte: <arquivo>)
🔢 Numeração: sequential (default)

Confirme com "ok" ou "tudo certo" para usar esses valores, OU
edite os que quiser ajustar (ex.: "stack: Bun + React + Elysia").
```

Se o usuário responder "ok" / "sim" / "confirma" / equivalente, prossegue.
Se editar algum campo, aplica a edição e reusa o resto.
Se o projeto estiver vazio (nenhuma fonte encontrada), fazer as 5 perguntas clássicas uma a uma, claramente sinalizando que não achou nada pra inferir.

### Step 3 — Create folder structure

Run in parallel via Bash:

```bash
mkdir -p docs/active docs/future docs/archive docs/discard
```

### Step 4 — Write template files

Read each template from this skill folder and write to the workspace, substituting placeholders:

| Template file | Destination |
|---|---|
| `templates/RULES.md` | `docs/RULES.md` |
| `templates/memory.md` | `docs/memory.md` |
| `templates/history.md` | `docs/history.md` |
| `templates/CLAUDE.md` | `CLAUDE.md` (only if doesn't exist) |

**Placeholders to substitute** (use Read then replace):

- `{{PROJECT_NAME}}` → resposta do usuário
- `{{PROJECT_DESC}}` → resposta do usuário
- `{{STACK}}` → resposta do usuário
- `{{DEV_COMMANDS}}` → resposta do usuário, envolvida em ```` ```bash ... ``` ````
- `{{NUMBERING}}` → resposta (sequential ou fase descrita)
- `{{TODAY}}` → data atual `YYYY-MM-DD`
- `{{NOW}}` → timestamp atual `YYYY-MM-DD HH:MM` (use current session time — se não souber, use `date` via bash)

Use the current real date/time — NEVER placeholder strings como "2024-01-01" ou timestamps do treinamento. Se precisar, rode `date +"%Y-%m-%d %H:%M"` via bash.

### Step 5 — Handle existing CLAUDE.md (merge mode)

Se `CLAUDE.md` já existe no root:

1. Read atual.
2. Procurar cabeçalho "Primeira coisa" ou "## Documentação" — se existir, avisar que há seção parecida e perguntar se user quer sobrescrever.
3. Se não existir: **appendar** (não substituir) uma seção nova logo após a introdução (ou no fim) com o conteúdo:

   ```markdown
   ## Documentação SPEC-driven — OBRIGATÓRIO

   Antes de qualquer código nesta sessão, ler:

   1. [docs/RULES.md](docs/RULES.md) — processo completo de documentação
      (pastas, ciclo de vida de specs, formato, timestamps).
   2. [docs/memory.md](docs/memory.md) — estado atual do projeto.

   Se houver spec ativa, ler também o session file dela.

   Resumo do processo:
   - Specs: `future/` → `active/` → `archive/` (ou `discard/`)
   - Toda spec ativa tem session file (log append-only)
   - Timestamps `YYYY-MM-DD HH:MM` em TUDO
   - Detalhes: [docs/RULES.md](docs/RULES.md)
   ```

   Usar Edit tool (old_string = final do arquivo existente, new_string = final + nova seção).

### Step 6 — Report

Listar em uma única mensagem:
- Arquivos criados (com caminhos)
- Arquivos modificados (se CLAUDE.md foi mesclado)
- Próximos passos sugeridos: "Revise `CLAUDE.md` e `docs/memory.md` com detalhes específicos do seu projeto. Quando tiver o primeiro trabalho, crie `docs/future/SPEC-001-<titulo>.md` ou mova direto para `active/` e inicie."

## Anti-patterns

- ❌ **Sobrescrever** `docs/` ou `CLAUDE.md` existentes sem confirmação
- ❌ Usar timestamps do treinamento ao invés de `date` do sistema
- ❌ **Perguntar info que já está em arquivo existente** — sempre inferir de `package.json`, `README.md`, `CLAUDE.md`, `pyproject.toml`, etc. antes
- ❌ Apresentar perguntas em branco ou em várias mensagens — mostrar tudo pré-preenchido em uma mensagem
- ❌ Commitar arquivos criados (deixar para o usuário decidir)
- ❌ Criar specs de exemplo — a pasta fica vazia, o usuário cria a SPEC-001 quando estiver pronto

## Templates location

Templates ficam ao lado deste SKILL.md em `templates/`:
- [templates/RULES.md](templates/RULES.md)
- [templates/memory.md](templates/memory.md)
- [templates/history.md](templates/history.md)
- [templates/CLAUDE.md](templates/CLAUDE.md)
