# SPEC-20261123-1613: Sanitizar o markdown do relatório e do chat (XSS)

**Status:** draft
**Porte:** P
**Owner:** @aliothbl
**Criada:** 2026-11-23 16:13
**Ativada:** —
**Concluída:** —
**Pausada em:** —
**Commit final:** —
**Keywords:** xss, markdown, v-html, sanitizacao, prompt-injection
**Features:** web, relatorio
**Branch:** —
**Programa:** —
**Workspace:** —
**Origem:** usuário em 2026-11-23 16:13 (backlog P0 item 3 de docs/DIAGNOSTICO-2026-11-23.md)
**Resumo:** A saída do LLM renderizada no relatório e no chat passa a ser escapada antes de virar HTML, fechando o XSS via prompt injection.

## Objetivo

`renderMarkdown` em `Step4Report.vue` e `Step5Interaction.vue` converte markdown por regex sem escapar HTML e injeta o resultado com `v-html`/`innerHTML` (7 ocorrências). O texto vem do LLM, que lê documentos enviados pelo usuário; um documento com prompt injection pode fazer o relatório executar script no navegador. A SPEC garante que nenhum HTML vindo do backend seja interpretado.

## Escopo

**DENTRO:**
- Escapar HTML (`& < > " '`) antes da conversão markdown→HTML nos dois componentes, ou passar a saída por um sanitizador (DOMPurify).
- Um único helper compartilhado (`frontend/src/utils/markdown.js`) usado pelos dois componentes.
- Teste do helper com payloads (`<img src=x onerror=...>`, `<script>`, `javascript:` em links).

**FORA:**
- Trocar o conversor regex por uma biblioteca de markdown completa (pode vir depois; não é necessário para fechar o XSS).
- Mitigação de prompt injection no backend (fora do alcance do frontend).

## Invariantes

- NUNCA texto vindo da API é inserido como HTML sem passar pelo helper.
- SEMPRE a formatação atual do relatório (títulos, listas, negrito, citações) continua igual para conteúdo legítimo.

## Implementação

Escapar primeiro e aplicar as regex de markdown depois (as regex só geram tags conhecidas); se o conversor gerar links, permitir apenas `http(s):`. DOMPurify como alternativa se o escape quebrar formatação.

### Modelo de dados

—

## Riscos

- O parse de saída em chinês por regex (`Step4Report.vue:557-567`) depende do texto cru — mitigação: escapar só no ponto de renderização, depois do parse.

## Sinais de sucesso

- Um relatório gerado a partir de documento com HTML malicioso mostra o HTML como texto.

## Critério de aceite

- [ ] Nenhum `v-html`/`innerHTML` em `frontend/src` recebe conteúdo que não passou pelo helper (verificado por grep).
- [ ] Teste do helper: `<img src=x onerror=alert(1)>` e `<script>` saem escapados; `[a](javascript:alert(1))` não gera link.
- [ ] Relatório existente renderiza com a mesma formatação visual (comparação manual de um relatório antes/depois).
- [ ] `vite build` sem erros.
