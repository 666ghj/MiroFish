# Equipe — claims, features compartilhadas, locks, worktrees, onboarding, multi-repo

> **PARE.** Este arquivo só se aplica com **`"team": "multi"` no manifesto** (`docs/.spec-system.json`) ou em cenário multi-repo. O regime é DECLARADO, nunca inferido: `solo` (default) dispensa esta rule; `multi` a torna obrigatória — o `activate` imprime a coreografia de publicação do claim e o `audit` avisa claim não-publicado. Virar multi = editar 1 linha do manifesto.

> Leia quando: `team: multi` no manifesto, ao ativar SPEC (claims), ao consolidar features, no onboarding de alguém, ou ao coordenar múltiplos repos.

## Claims — trabalho em voo visível em main (R.11)

`docs/active/` é vazio em main (R.2); quem anuncia trabalho em voo é `docs/claims/SPEC-<id>.md` — 1 arquivo por SPEC = zero conflito de merge. Formato (~10 linhas):

```
**SPEC:** SPEC-20260702-1500-checkout-descontos
**Título:** Descontos no checkout
**Owner:** @maria
**Branch:** feature/checkout-descontos
**Features:** checkout, billing
**Ativada em:** 2026-07-02 15:00
```

- **Ciclo:** `specctl activate` cria o claim; `pause`/`archive`/`discard` removem; `resume` recria. Invariante: claim existe ⇔ SPEC ativa.
- **Publicação (team: multi):** o claim nasce na branch e precisa correr NA FRENTE do trabalho — publique na base via **PR trivial** (diff só em `docs/claims/` — merge imediato/auto-merge quando a política permitir). O `specctl activate` imprime os comandos exatos; a coreografia é:
  ```
  git checkout -b claim/SPEC-<id> <base>
  git checkout <branch-de-feature> -- docs/claims/SPEC-<id>.md
  git commit -m "docs: claim SPEC-<id> (R.11)" && git push -u origin claim/SPEC-<id>
  # PR para <base> (auto-merge) e volte: git checkout <branch-de-feature>
  ```
  O `audit` avisa claim local ainda não presente na base. Fallback sem automação: draft PR da branch na ativação (visibilidade via PRs abertas). Em `team: solo`, nada disso se aplica — o claim vai à base junto do merge de trabalho.
- **Antes de criar SPEC:** consultar `docs/claims/` — o brief da sessão já lista claims que colidem com as features tocadas. Colisão → alertar o usuário e coordenar com o Owner do claim ANTES de criar SPEC duplicada ("SPEC-x de @maria já toca `auth` — coordenar ou prosseguir?").
- **Higiene (audit):** claim sem SPEC ativa correspondente = órfão (warn); ativação sem claim = warn.

## features/<area>.md em equipe

- **Line-oriented:** nas seções compartilhadas (Specs desta feature, Decisões, Alternativas rejeitadas, Gotchas), cada entrada é UMA linha iniciada por SPEC-id ou DEC-id. O timestamp do id ordena; conflito de merge vira inserção adjacente trivial. Nunca reordenar linhas existentes.
- **Decisões:** `DEC-YYYYMMDD-HHMM-slug` com status `ativa | obsoleta → DEC-x | substituída por SPEC-y`. Obsoletar = mudar o campo status da linha; nunca reescrever nem deletar.
- **Gotchas:** sufixo de recorrência `(citado por: SPEC-a, SPEC-b)`. SPEC que tropeça no mesmo gotcha ADICIONA seu id; ≥3 SPECs → candidato a promoção no fechamento (ver `docs/rules/lifecycle.md`).
- **Estado atual (prosa):** nunca editar concorrentemente. SPEC que arquiva APENDA `### Delta de estado (SPEC-<id>, data)` ao fim da seção. A consolidação dos deltas na prosa canônica é **single-writer**: sessão dedicada com dono (CODEOWNERS por feature é o candidato natural); consolide quando 3-5 deltas acumularem — é tarefa legítima de SPEC de manutenção.
- **Tamanho:** feature viva não tem teto (nº de features ilimitado, não lintado). Se o auto-load N1 pesar demais, `rollup` opcional move o conteúdo mais antigo para `<area>.history.md` — mover, nunca deletar (R.5).

## Lock leve de sessão

1 SPEC = no máximo 1 sessão de ESCRITA por vez.

- Sessão de escrita cria `tmp/session.lock` na pasta da SPEC com o id da sessão por timestamp (ex.: `sessao-20260702-1530`). `tmp/` é gitignored — o lock nunca entra no repo.
- Encontrou lock existente → NÃO escrever no journal; perguntar ao usuário (a outra sessão pode ter morrido; ele decide sobrescrever).
- Sessão somente-leitura: dispensa lock e é PROIBIDA de tocar o journal.
- Fim da sessão de escrita: remover o lock.

## Worktrees

**1 worktree = 1 branch = 1 SPEC ativa.** `docs/active/` diverge entre worktrees por design (cada worktree enxerga só a própria SPEC). Nunca duas SPECs ativas no mesmo worktree (com >1 pasta em active/, o specctl exige escolha explícita); nunca a mesma SPEC em escrita em dois worktrees (o lock acima cobre).

## Onboarding

**Trilha (nesta ordem, do panorama ao detalhe):**

1. `docs/ARCHITECTURE.md` — mapa transversal região→feature
2. `docs/CONSTITUTION.md` — princípios do projeto
3. `docs/INDEX.md` — roteamento feature→arquivos
4. `docs/features/<area>.md` das áreas em que vai trabalhar
5. `docs/ARCHIVE-INDEX.md` filtrado pela área
6. `digest.md` das SPECs relevantes do archive

Custo: orientação global por poucos milhares de tokens, sem arqueologia de código.

**Tours guiados — `docs/tours/<persona>-<foco>.md`** (ex.: `novo-dev-checkout.md`, `revisor-auth.md`). Markdown puro, sem dependência de extensão/ferramenta. Cada passo segue **SMIG**:

- **Situação** — onde você está no fluxo e por que este passo existe
- **Mecanismo** — como o código faz (com âncora `arquivo:linha`)
- **Implicação** — o que isso impõe ao resto do sistema
- **Gotcha** — o que morde quem mexe aqui

Âncoras `arquivo:linha` são VERIFICADAS ao escrever e re-verificadas a cada edição do tour. Âncora quebrada = passo desatualizado: corrigir ou remover, nunca deixar apodrecer. Tours têm arco narrativo (começo→fim de um fluxo real), não são lista solta de arquivos.

## Multi-repo — federação com camada de produto fina

Regra estrutural: **documentação de execução mora com o código** — o gate por diff do PR, a branch da SPEC e a sessão da IA são locais ao repo; repo-só-de-docs quebra a validação atômica código+docs. **Só coordenação e visão transversal sobem**, e a camada de produto é ~90% gerada ou manifesto — nunca a memória viva das SPECs.

**Camada de produto** (começa num repo-casa designado, ex.: o back; meta-repo dedicado só quando repos/times crescerem):

- ARCHITECTURE do produto — mapa de repos: qual repo é dono de quê, fluxos entre eles
- CONSTITUTION do produto — princípios compartilhados, herdados pelos por-repo
- `programs/` cross-repo — 1 programa, 1 SPEC por repo, nós com prefixo `repo_id:` (ver `docs/rules/programs.md`)
- BOARD federado — agregação dos `docs/claims/` (e PRs abertas) de todos os repos, gerado por automação do repo-casa: a visão de voo do produto
- INDEX federado (opcional) — concatenação com namespace (`back/auth`, `front/checkout`)

No manifesto de cada repo: `"product": { "home": "<repo/path>", "repo_id": "<id>" }`. O brief local puxa a headline federada quando configurado.

**Feature que existe nos dois lados** (ex.: checkout): cada repo documenta o SEU lado (`checkout-api` no back, `checkout-ui` no front); o programa e a ARCHITECTURE do produto fazem o link. NUNCA um arquivo de feature compartilhado entre repos — longe dos dois códigos, apodrece.

**Tabela de decisão:**

| Cenário | Estrutura |
|---|---|
| 1 repo | v4 pura, sem camada de produto |
| 2-5 repos, cross-repo ocasional | repo-casa designado |
| Muitos repos/times, cross-repo frequente | meta-repo dedicado (pequeno: manifestos + gerados) |
| Toda feature cruza tudo | o problema é o recorte de repos → considere monorepo (TAXONOMY por namespace cobre nativamente) |

Onboarding multi-repo: começa na ARCHITECTURE do produto e desce à trilha do repo.
