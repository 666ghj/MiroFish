# Retrieval — histórico via subagente (Nível 3)

> **PARE.** Este arquivo só se aplica ao investigar SPECs arquivadas (archive/discard, journal de SPEC não-ativa, `*.history.md`). Cobre: leitura via subagente e o protocolo DISPATCH→EVALUATE→REFINE→LOOP. Fora disso, o brief/--help respondem.

> Referência sob demanda (R.8). Leia quando a tarefa exigir histórico: docs/archive/**, docs/discard/**, journal de SPEC não-ativa ou features/*.history.md.

## Read direto × subagente

| Alvo | Como ler |
|---|---|
| main.md + SNAPSHOT da SPEC ativa; features do escopo; INDEX; ARCHITECTURE | Read direto (barato, livre) |
| docs/ARCHIVE-INDEX.md | Read direto (1 linha por SPEC) |
| docs/archive/**, docs/discard/**, journal de SPEC ≠ ativa, *.history.md | SUBAGENTE isolado — o hook guard-read NEGA Read direto no contexto principal |

Exceção auditada: um arquivo `.allow-read` na pasta da SPEC ativa libera Reads específicos. Use raramente e registre `[nota]` no journal com o motivo.

Regra de ouro: o custo de contexto escala com o escopo da TAREFA, nunca com a idade do projeto. Histórico só entra na janela principal como retorno destilado.

## Rota canônica (do barato ao caro)

1. `docs/ARCHIVE-INDEX.md` — filtre por keyword/feature (id, status, features, keywords, resumo em 1 linha).
2. `digest.md` das candidatas (≤2.000 bytes cada) — responde a maioria das perguntas de histórico.
3. `journal.md`/`main.md` da SPEC — SÓ se o digest não bastar, e SÓ dentro do subagente.

## Protocolo do subagente: DISPATCH → EVALUATE → REFINE → LOOP (máx 3 ciclos)

1. **DISPATCH** — busca ampla: keywords da tarefa no ARCHIVE-INDEX + features relacionadas. Não superespecifique a primeira consulta.
2. **EVALUATE** — pontue cada fonte de 0 a 1: ≥0,8 responde diretamente; 0,5–0,7 decisão/padrão relacionado; <0,2 exclua com confiança (não volta a ser relevante). Registre LACUNAS explícitas ("achei O QUE mudou; falta o PORQUÊ").
3. **REFINE** — incorpore o vocabulário real do projeto revelado no ciclo 1 (ex.: o código diz "throttle", não "rate limit"); exclua o irrelevante; mire as lacunas.
4. **LOOP** — repita com a consulta refinada. PARE quando houver ≥3 fontes com score ≥0,7 e nenhuma lacuna crítica: **3 arquivos certos > 10 medianos**. Esgotados os 3 ciclos, devolva o melhor conjunto + lacunas restantes declaradas.

## Formato do retorno (≤500 tokens — obrigatório)

- **Resposta:** 1–3 frases diretas à pergunta.
- **Fontes:** SPEC-id/arquivo por afirmação.
- **Decisões/gotchas:** DEC-ids e gotchas pertinentes, 1 linha cada.
- **Lacunas:** o que NÃO foi encontrado — declare, não invente.

PROIBIDO colar conteúdo bruto de journal/main no retorno.

## Exemplo mínimo

```
Pergunta: por que abandonamos cache em Redis?
Ciclo 1 — DISPATCH: ARCHIVE-INDEX, grep "redis|cache" → SPEC-20250412-0910-cache-redis (discarded, feature infra/fila).
Ciclo 2 — digest: "latência de rede anulou o ganho; ver DEC-20250413-1120-sqs-memoria". Lacuna: números do benchmark → journal, entrada [tentativa] de 2025-04-13.
Retorno (5 linhas): resposta + DEC-id + ponteiro ao journal + lacuna "benchmark de escrita nunca foi medido".
```

## Quando NEM subagente

Pergunta sobre a SPEC ativa ou o estado vigente de uma feature mora nos Níveis 0–2 (SNAPSHOT, main.md, features/<area>.md): leia direto. Subagente é para arqueologia, não para o presente.
