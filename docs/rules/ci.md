# CI — docs-gate (guia para humanos)

> **PARE.** Este arquivo só se aplica ao configurar/debugar CI. Cobre: os passos do docs-gate, branch protection, exit codes, troubleshooting, portes GitLab/Azure. Fora disso, o brief/--help respondem.

> Leia quando: configurar o repositório/branch protection, o docs-gate falhar num PR, ou portar o gate para GitLab/Azure.

O CI é o piso universal de enforcement: alcança qualquer dev, CLI e modelo — hooks locais são conveniência; o gate é ele. Instalado pelo init em `.github/workflows/docs-gate.yml`. Todo check chama o MESMO código que roda localmente (`scripts/specctl.mjs`) — o que passa local passa no CI.

## O que roda em cada PR (nesta ordem)

| # | Passo | Comando | Valida |
|---|---|---|---|
| 1 | checkout | `fetch-depth: 0` | histórico completo — sem ele a base do PR é indeterminável |
| 2 | lint | `node scripts/specctl.mjs lint --strict` | estrutura de pastas; campos/seções do main.md; coerência pasta↔status (incluindo future/); journal (SNAPSHOT nas 60 primeiras linhas, tipos de LOG); features (formato, DEC-ids únicos — SEM teto de tamanho); TAXONOMY cobre toda feature; ROADMAP sem entradas mortas (warn); cobertura RF quando prd.md existe; orçamentos das camadas sempre-carregadas (CLAUDE ≤6KB, AGENTS ≤6,2KB, RULES ≤5KB, digest ≤2KB — INDEX e features não têm teto); índices gerados idempotentes (INDEX, ARCHIVE-INDEX, PROGRAMS, DEFERRED); secret-scan em docs/ (R.15) |
| 3 | audit do diff | `node scripts/specctl.mjs audit --pr --base <sha-base-do-evento>` | julga o DIFF: SPEC que saiu de active/ tem destino classificado — archive → critérios fechados/aceitos + digest + R.7 por conteúdo; discard → justificativa + digest; future → Pausada em — e fechamento incompleto é BLOQUEADO; artefatos de pipeline sem contrapartida no journal (warn) |
| 4 | dependências | `node scripts/specctl.mjs audit --deps` | programas: nós existem, sem ciclos, coerência status×DAG |
| 5 | gate de main (só PR → main) | `node scripts/specctl.mjs audit --main-gate` | `docs/active/` vazio após o merge (R.2) |
| 6 | index-check | regenera os índices no checkout e falha se `git diff --exit-code -- docs/INDEX.md docs/ARCHIVE-INDEX.md docs/PROGRAMS.md` detectar diferença | INDEX/ARCHIVE-INDEX/PROGRAMS commitados = regeneração exata (ninguém editou os gerados à mão) |

**Push em main:** se docs/ mudou, regenera ARCHIVE-INDEX/INDEX e commita com `[skip ci]` (exige `contents: write` no workflow).
**Schedule semanal:** `audit` completo — staleness >30d (por conteúdo, nunca mtime), claims órfãos, decisões >180d, SPECs fantasma.

## Branch protection (obrigatório — sem isso o gate é decorativo)

GitHub → Settings → Branches → Add branch protection rule para `main`:

1. Require a pull request before merging
2. Require status checks to pass before merging → selecionar os checks do `docs-gate`
3. (Recomendado) Require branches to be up to date before merging

## Exit codes

| Código | Significado |
|---|---|
| 0 | passou — warnings podem existir (aparecem no log, não bloqueiam) |
| 1 | erro/bloqueio — o job falha; a mensagem lista as pendências e o caminho de saída |
| 2 | reservado aos HOOKS locais (deny de PreToolUse) — nunca ocorre em CI; se ocorrer, é bug do specctl, reporte |

## Troubleshooting

| Sintoma | Causa | Correção |
|---|---|---|
| `audit --pr` falha com base indeterminável | shallow clone | confirme `fetch-depth: 0` no checkout. O audit falha FECHADO por design — nunca passa em vácuo |
| index-check com diff | INDEX/ARCHIVE-INDEX editado à mão ou desatualizado | rode `node scripts/specctl.mjs index` localmente e commite; nunca edite os gerados |
| main-gate falhou | PR para main contém SPEC em `docs/active/` | feche (`/spec fechar` → archive), descarte ou pause a SPEC antes do merge |
| audit bloqueou archive | fechamento incompleto | resolva o que a mensagem listar: critérios `[ ]` sem `[aceito-incompleto: ...]`, digest.md ausente, `[conclusão]` ausente no LOG, `Commit final: —`, feature sem o SPEC-id em Concluídas |
| secret-scan ERRO | segredo em docs/ | substitua por `<REDACTED:tipo>` + `[nota]` da redação no journal (exceção auditada ao append-only, R.15) e ROTACIONE o segredo exposto |
| lint: coerência pasta↔status | status do main.md não bate com a pasta (ex.: `done` fora de archive/) | use as transições do specctl (`pause/resume/archive/discard`), nunca `mv` manual |
| `audit --deps`: ciclo/nó inexistente | manifesto de programa inválido | edite `docs/programs/<slug>.md` em PR dedicado (single-writer) |
| regeneração em main falhou (push negado) | workflow sem permissão de escrita | Settings → Actions → General → Workflow permissions → Read and write |

## Nota de compatibilidade: hooks × CI (custo por tool-call)

Os hooks locais (guard-read, guard-write, stamp-check) executam `node scripts/specctl.mjs ...` a CADA Read/Write/Edit da sessão — o start do Node domina o custo (dezenas de ms por chamada). Aceitável em disco local; perceptível em FS de rede ou containers frios. Se pesar, é legítimo desativar hooks pontualmente: **o CI continua sendo o piso — nada errado mergeia, só é pego mais tarde**. CLIs sem suporte a hooks (não-Claude Code) operam com AGENTS.md (texto) + este gate; a experiência é desigual por construção, o gate não.

## GitLab / Azure (equivalentes mínimos — lint + audit do diff + deps)

GitLab (`.gitlab-ci.yml`):

```yaml
docs-gate:
  image: node:20
  variables: { GIT_DEPTH: "0" }
  rules: [{ if: '$CI_PIPELINE_SOURCE == "merge_request_event"' }]
  script: ["node scripts/specctl.mjs lint --strict", "node scripts/specctl.mjs audit --pr --base $CI_MERGE_REQUEST_DIFF_BASE_SHA", "node scripts/specctl.mjs audit --deps"]
```

Azure Pipelines (`azure-pipelines.yml`):

```yaml
steps:
  - checkout: self
    fetchDepth: 0
  - script: node scripts/specctl.mjs lint --strict && node scripts/specctl.mjs audit --pr --base $(git merge-base origin/$(System.PullRequest.TargetBranchName) HEAD) && node scripts/specctl.mjs audit --deps
    displayName: docs-gate
```

Main-gate, index-check e o schedule semanal portam-se por analogia ao YAML do GitHub — mesmos comandos specctl, só o wrapper muda.
