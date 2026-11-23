# Bugs — [Nome da Funcionalidade]

> **Contrato deste arquivo:** entradas são APPEND-ONLY — nunca sobrescrever ou deletar bugs existentes; apenas adicionar novos e atualizar o campo **Status**. IDs contínuos (BUG-01, BUG-02, ... — sempre continuar do maior ID existente, mesmo entre execuções de QA). Em re-execução de QA, todo bug com Status `Corrigido` DEVE ser re-testado e atualizado para `Verificado` ou `Reaberto`.

## BUG-NN

- **Requisito afetado:** RF-XX
- **Severidade:** Alta | Média | Baixa
- **Status:** Aberto | Corrigido | Verificado | Reaberto | Não reproduzível
- **Descrição:** [o que está errado, em 1-2 frases]
- **Passos de reprodução:**
  1. [passo]
  2. [passo]
- **Esperado:** [comportamento esperado]
- **Observado:** [comportamento observado]
- **Evidência:** evidence/BUG-NN-[label].png
- **Correção aplicada:** — _(preenchido pelo executar-bugfix: descrição breve + commit)_
- **Testes de regressão:** — _(preenchido pelo executar-bugfix: lista de testes criados)_
