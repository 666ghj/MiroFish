# SPEC-20261123-1613: Validar IDs de projeto, simulação e relatório antes de usar em caminhos

**Status:** draft
**Porte:** P
**Owner:** @aliothbl
**Criada:** 2026-11-23 16:13
**Ativada:** —
**Concluída:** —
**Pausada em:** —
**Commit final:** —
**Keywords:** path-traversal, ids, validacao, filesystem
**Features:** infra, ambiente, simulacao, relatorio
**Branch:** —
**Programa:** —
**Workspace:** —
**Origem:** usuário em 2026-11-23 16:13 (backlog P0 item 5 de docs/DIAGNOSTICO-2026-11-23.md)
**Resumo:** IDs recebidos pela API são validados contra o formato gerado pelo próprio backend antes de virar caminho em disco.

## Objetivo

`simulation_id`, `report_id` e `project_id` vindos do corpo JSON vão direto para `os.path.join`, e `SimulationManager._get_simulation_dir` faz `makedirs` de qualquer ID (`simulation_manager.py:152-156`). Um ID com `../` permite criar ou ler diretórios fora de `backend/uploads/`. Os IDs reais têm formato fixo (`proj_`, `sim_`, `report_` + 12 hex), o que torna a validação simples.

## Escopo

**DENTRO:**
- Validadores `is_valid_project_id`, `is_valid_simulation_id`, `is_valid_report_id` (regex `^(proj|sim|report)_[0-9a-f]{12}$`) num módulo único.
- Aplicação nos pontos de entrada da API (path e corpo JSON) com resposta 400.
- Defesa em profundidade nos helpers de diretório (`_get_simulation_dir`, `_get_project_dir`, diretório de relatório): validar e confirmar via `realpath` que o caminho fica dentro da raiz de uploads.
- `_get_simulation_dir` deixa de criar diretório em leituras (só em `create`).

**FORA:**
- `graph_id` do Zep (não vira caminho local).
- Parâmetro `platform` em `/posts` (já limitado por sufixo e existência; baixo risco).

## Invariantes

- NUNCA um caminho derivado de entrada do usuário resolve para fora de `backend/uploads/`.
- SEMPRE IDs gerados pelo próprio backend continuam aceitos (compatível com dados existentes).

## Implementação

Validação na borda (handlers) + assert de contenção nos helpers. Conferir o formato real dos IDs existentes em `backend/uploads/` antes de fixar a regex.

### Modelo de dados

—

## Riscos

- IDs antigos fora do formato (versões anteriores do upstream) deixam de abrir — mitigação: verificar `backend/uploads/` local e aceitar o formato legado se existir.

## Sinais de sucesso

- Nenhuma rota aceita ID que não tenha sido gerado pelo backend.

## Critério de aceite

- [ ] Teste: `simulation_id="../../tmp/x"` no corpo de `/api/simulation/prepare`, `/start` e `/api/report/generate` retorna 400 e não cria diretório.
- [ ] Teste: helpers de diretório recusam ID inválido mesmo chamados diretamente.
- [ ] Projetos, simulações e relatórios existentes em `backend/uploads/` continuam abrindo na UI.
- [ ] Suíte do backend verde.
