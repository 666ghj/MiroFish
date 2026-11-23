# Template de Especificação Técnica

## Resumo Executivo

[Forneça uma breve visão técnica da abordagem de solução. Resuma as decisões arquiteturais principais e a estratégia de implementação em 1-2 parágrafos.]

## Arquitetura do Sistema

### Visão Geral dos Componentes

[Breve descrição dos componentes principais e suas responsabilidades:

- Nomes dos componentes e funções primárias **Não deixe de listar cada um dos componentes novos ou que serão modificados**
- Relacionamentos principais entre componentes
- Visão geral do fluxo de dados]

## Design de Implementação

### Interfaces Principais

[Defina interfaces de serviço principais (≤20 linhas por exemplo, na linguagem principal do projeto):

```
// Exemplo em pseudocódigo — use a linguagem do projeto
interface NomeServico {
    nomeMetodo(entrada: Tipo): Saida
}
```

]

### Modelos de Dados

[Defina estruturas de dados essenciais:

- Entidades de domínio principais (se aplicável)
- Tipos de requisição/resposta
- Esquemas de banco de dados (se aplicável)]

### Endpoints de API

[Liste endpoints de API se aplicável:

- Método e caminho (ex: `POST /api/v0/recurso`)
- Breve descrição
- Referências de formato requisição/resposta]

## Pontos de Integração

[Inclua apenas se a funcionalidade requer integrações externas:

- Serviços ou APIs externos
- Requisitos de autenticação
- Abordagem de tratamento de erros]

## Abordagem de Testes

### Testes Unidade

[Descreva estratégia de testes unidade:

- Componentes principais a testar
- Requisitos de mock (apenas serviços externos)
- Cenários de teste críticos]

### Testes de Integração

[Se necessário, descreva testes de integração:

- Componentes a testar juntos
- Requisitos de dados de teste]

### Testes de E2E

[Se necessário, descreva testes E2E:

- Teste o frontend junto com o backend **usando a ferramenta E2E do projeto (ex.: Playwright)**]

## Sequenciamento de Desenvolvimento

### Ordem de Construção

[Defina sequência de implementação:

1. Primeiro componente/funcionalidade (por que primeiro)
2. Segundo componente/funcionalidade (dependências)
3. Componentes subsequentes
4. Integração e testes]

### Dependências Técnicas

[Liste quaisquer dependências bloqueantes:

- Infraestrutura requerida
- Disponibilidade de serviço externo]

## Monitoramento e Observabilidade

[Defina abordagem de monitoramento usando a infraestrutura de observabilidade EXISTENTE do projeto (se nenhuma existir, proponha o mínimo viável — não invente stack):

- Métricas a expor (no formato da stack de métricas do projeto)
- Logs principais e níveis de log
- Integração com os dashboards/ferramentas já usados pelo projeto]

## Considerações Técnicas

### Decisões Principais

[Documente decisões técnicas importantes:

- Escolha de abordagem e justificativa
- Trade-offs considerados
- Alternativas rejeitadas e por quê]

### Riscos Conhecidos

[Identifique riscos técnicos:

- Desafios potenciais
- Abordagens de mitigação
- Áreas precisando pesquisa]

### Conformidade com Skills Padrões

[Pesquise as skills aplicáveis — pasta `.claude/skills/` do projeto e skills de usuário relevantes (ex.: frontend-design para features de UI) — e liste-as abaixo:]

### Arquivos relevantes e dependentes

[Liste aqui arquivos relevantes e dependentes]
