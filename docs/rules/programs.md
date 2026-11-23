# Programas — R.14

> **PARE.** Este arquivo só se aplica se `docs/programs/` tem manifesto (trabalho em 2+ SPECs com dependências entre si). Cobre: o formato do DAG, derivação de ordem/`Bloqueia`, `audit --deps`, `next`, cross-repo. Fora disso, o brief/--help respondem.

> Leia quando: um trabalho abranger 2+ SPECs com dependências entre si, ao criar/editar `docs/programs/<slug>.md`, ou quando `audit --deps` reclamar.

## O que é um programa

Programa = DAG de SPECs com dependências. Dois níveis de ordenação, zero sobreposição: o **programa ordena SPECs**; **tasks ordenam dentro de uma SPEC**. Se o trabalho cabe numa SPEC (mesmo porte G, com fases), NÃO é programa. Feature gigante que não cabe num arco único vira programa: cada bloco vira SPEC própria.

## Épico/pilar = programa (fatiar É criar programa)

Demanda grande demais para um arco único ("épico", "pilar", "fatias") é EXATAMENTE o caso de programa: cada fatia = SPEC própria (nó do grafo, `**Programa:** <slug>`); o que falta = nós `draft` em future/; progresso = **derivado** (`Ndone/Ntotal` no PROGRAMS.md gerado; `next` aponta o próximo nó).

**ANTI-PADRÃO (proibido):** manter uma "SPEC-contêiner" eternamente em `future/` como guarda-chuva do épico, com progresso mantido À MÃO numa seção de prosa (tabela de "fatias entregues/restantes"). Isso reinventa o programa fora da ferramenta: PROGRAMS.md/`next`/brief ficam CEGOS ao trabalho real, o contador congela, e a tabela manual é dual-write (viola "derivado nunca é escrito"). SPEC é contrato que FECHA — não contêiner. Mapa de "o que falta" que ainda não merece SPECs future é rascunho de planejamento (`.scratch/`), nunca a fonte de progresso.

## Manifesto único — `docs/programs/<slug>.md`

TODO o grafo vive num único arquivo, em main. Formato literal — nada além disto:

```
# Programa: <slug>

**Owner:** @handle

- SPEC-<id> | depende de: —
- SPEC-<id2> | depende de: SPEC-<id>
- SPEC-<id3> | depende de: SPEC-<id>, SPEC-<id2>
```

Uma linha por nó. `depende de:` recebe `—` (nó raiz) ou SPEC-ids separados por vírgula. O main.md de cada SPEC participante declara apenas `**Programa:** <slug>` (preenchido por `specctl new <slug> --program <p>` ou editado com validação do lint) — **nenhum campo de dependência no main.md**.

## Semântica: derivado nunca é escrito

`Bloqueia:` e a ordem topológica são DERIVADOS do manifesto — nunca escritos à mão, em lugar nenhum (nem no manifesto, nem no main.md, nem nas features). "O que SPEC-a bloqueia" = inversão das arestas. "O que posso pegar agora" = nós cujas dependências estão todas `done`. Escrever `Bloqueia:` à mão é bug: era o dual-write da v3, fisicamente impossível entre branches — o manifesto único em main mata a raiz do problema.

## Single-writer

O manifesto vive em main e é editado por **PR dedicado** (decisão de coordenação, como taxonomia) — nunca de dentro da branch de uma SPEC junto com código. Qualquer dev propõe; o Owner do programa mergeia. Nós concluídos permanecem no manifesto (histórico do grafo); o programa "termina" quando todo nó está `done`/`discarded` — o arquivo fica.

## Validação — `node scripts/specctl.mjs audit --deps`

| Check | Severidade |
|---|---|
| Nó do manifesto sem pasta SPEC correspondente | erro |
| SPEC declara `**Programa:**` que não existe em docs/programs/ | erro |
| Ciclo no grafo | erro |
| Coerência status×DAG: nó `active` ou `done` com dependência ainda não-`done` | warn |
| Coerência status×DAG: dependência `discarded` de nó vivo (aresta a re-planejar) | warn |

O status vem do main.md de cada SPEC (fonte única); o manifesto NÃO tem campo de status. Ativar SPEC cuja dependência não está `done` gera warn, não bloqueio — desbloqueio antecipado é negociação com o Owner do nó dependido (o claim em `docs/claims/` diz quem é). O docs-gate roda `audit --deps` em todo PR.

## Descoberta — `docs/PROGRAMS.md` (gerado) e `specctl next`

Definir o grafo não basta; alguém precisa LER o backlog para saber o próximo trabalho — sem vasculhar todos os manifestos. Duas peças fecham isso:

- **`docs/PROGRAMS.md`** é GERADO por `specctl index` (junto com INDEX/ARCHIVE-INDEX; `> GERADO — NÃO EDITAR`). Um bloco por programa com status **derivado**: `## <slug> — aberto|concluído · Ndone/Ntotal · owner` + linhas `prontos:` / `em progresso:` / `bloqueados: (aguarda X)` / `pausados:` / `concluídos:` (enumera os nós done — é o que torna o bloco de um programa concluído um mapa histórico das suas SPECs). Descoberta O(1): 1 arquivo mostra todos os programas, seus próximos nós e o que já entregaram. Os rótulos NÃO são gravados — são recomputados do `Status` real a cada `index`/`next`/brief: fechar a dependência move o nó de `bloqueados` para `prontos` SOZINHO ("pendentes" = prontos + bloqueados; a subdivisão diz o que já é pegável AGORA).
- **`node scripts/specctl.mjs next [--program <slug>]`** computa sob demanda o próximo trabalho, cruzando o grafo com o status real das SPECs: **▶ prontos** (draft com todas as deps `done`), **⏳ ativos**, **🔒 bloqueados** (com qual dep falta). Também lê o ROADMAP e lista o backlog não-priorizado (ver `lifecycle.md`).

Status derivado (nunca escrito): programa **aberto** = ≥1 nó não-`done`; **concluído** = todos `done`/`discarded`. Nó **pronto** = `draft` + deps todas `done`. O **brief** do SessionStart injeta o resumo (programas abertos + próximo nó) — o modelo vê o que pegar ao abrir a sessão, sem ler os manifestos. Programa concluído NÃO é movido nem deletado: o manifesto permanece em `main` como histórico do grafo.

## Cross-repo (multi-repo)

Trabalho que cruza repositórios = um programa com **uma SPEC por repo**. O manifesto mora na camada de produto (repo-casa — ver `docs/rules/team.md`); nós levam prefixo `repo_id:` (o `repo_id` do `docs/.spec-system.json` de cada repo):

```
# Programa: checkout-v2

**Owner:** @maria

- back:SPEC-20260702-1010-checkout-api | depende de: —
- front:SPEC-20260703-0930-checkout-ui | depende de: back:SPEC-20260702-1010-checkout-api
```

Cada SPEC cavalga a própria branch/PR com enforcement local completo. O `audit --deps` local valida integralmente os nós do próprio repo; nós prefixados de outros repos estão fora do alcance do lint local — a coerência cross-repo é conferida na camada de produto (BOARD federado, relatório agregado do repo-casa).

## Exemplo completo (single-repo)

```
# Programa: billing-v2

**Owner:** @joao

- SPEC-20260701-0900-billing-schema | depende de: —
- SPEC-20260702-1400-billing-api | depende de: SPEC-20260701-0900-billing-schema
- SPEC-20260703-0800-billing-migracao | depende de: SPEC-20260701-0900-billing-schema
- SPEC-20260702-1410-billing-ui | depende de: SPEC-20260702-1400-billing-api
```

Leitura derivada: schema bloqueia api e migracao; api bloqueia ui. Ordem topológica: schema → (api ∥ migracao) → ui. Coerência: se `billing-ui` está `active` com `billing-api` ainda `active`, o audit avisa — ou a ativação foi prematura, ou a aresta está errada; ambas se resolvem em PR dedicado ao manifesto ou conversa com o Owner.
