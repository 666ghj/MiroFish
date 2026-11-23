> PARE. Este arquivo só se aplica a Porte G com pipeline. Cobre: templates de prd/techspec/tasks/NN_task/qa/review/bugfix. Fora disso, formats.md core responde.

# Templates do pipeline (rules/formats-pipeline.md)

Artefatos opcionais de porte G, na RAIZ da pasta da SPEC (ou no workspace declarado — rules/interop.md), declarados por ponteiro no `main.md` logo após o cabeçalho, com timestamp de geração (ponteiro sem arquivo = warn):

```markdown
**PRD:** prd.md (YYYY-MM-DD HH:MM)
**TechSpec:** techspec.md (YYYY-MM-DD HH:MM)
**Tasks:** tasks.md (YYYY-MM-DD HH:MM)
```

Mesmos nomes/moldes do harness prd (`tasks/prd-<slug>/`) — projetos alternam entre standalone e harness sem retrabalho.

**Convenção RF-N (global):** requisitos funcionais numerados `RF-1..RF-n` com numeração GLOBAL e sequencial no `prd.md` inteiro (nunca reinicia por seção). Todo RF coberto por ≥1 critério do main.md via `(cobre RF-n)` — lint valida quando `prd.md` existe. **Altitude de RF:** o RF nomeia a capacidade e o serviço (O QUÊ), nunca o mecanismo (COMO — transporte, endpoint, header, lib); mecanismo pertence à techspec (ex.: "Slack (OUTPUT)", não "Slack incoming-webhook") — o RF fica estável quando a decisão de implementação evolui.

## Procedimentos mínimos por artefato

(Destilados do harness; quando o rigor máximo importar, use o harness via interop.)

- **PRD:** ler main.md+journal ANTES e perguntar SÓ o que ainda não foi respondido (dedupe); clarificar com o usuário antes de redigir; PRD = O QUÊ/POR QUÊ, <2.000 palavras, ZERO solução de design; RF na altitude de capacidade (nunca mecanismo — ver Convenção RF-N acima); refinar critérios do main.md com `(cobre RF-n)` — mudança de contrato = validação humana.
- **TechSpec:** pesquisar ANTES (padrões do próprio código + docs das libs); techspec = COMO, NÃO repete o PRD; decisões com efeito além da SPEC → `[decisão]` no journal (sobem a features no fechamento).
- **Tasks:** propor a lista de ALTO NÍVEL e obter aprovação ANTES de gerar os `NN_task.md`; máx 15 tasks; cada task = entregável funcional incremental COM a própria suíte de testes.
- **QA/evidência:** evidência bruta em `tmp/`; a citada → `evidence/` com nome determinístico; QA aprovado marca critérios cobertos no main.md com evidência (R.6.1); qa-report REJECTED ou bug High aberto bloqueia archive quando esses artefatos existem.

## 1. Template `prd.md`

```markdown
# PRD — [Funcionalidade]

**Origem:** local | importado (time X, YYYY-MM-DD, vN)

## Visão Geral
[Qual problema resolve, para quem, por que é valioso.]

## Objetivos
[Objetivos específicos e mensuráveis: como é o sucesso, métricas principais, objetivos de negócio.]

## Histórias de Usuário
[Como [tipo de usuário], quero [ação] para que [benefício]. Personas primárias e secundárias; fluxos principais e casos extremos.]

## Funcionalidades Principais
[Para cada funcionalidade: o que faz, por que importa, como funciona em alto nível.
Requisitos funcionais numerados RF-1..RF-n — numeração GLOBAL do documento.]

## Experiência do Usuário
[Personas e necessidades; fluxos e interações principais; UI/UX; acessibilidade.]

## Restrições Técnicas de Alto Nível
[SÓ restrições — soluções de design pertencem à techspec: integrações externas, conformidade/regulatório/segurança, metas de performance/escalabilidade, sensibilidade de dados/privacidade, tecnologia/protocolo não negociáveis.]

## Fora de Escopo
[O que esta funcionalidade NÃO incluirá: exclusões explícitas, considerações futuras, limites.]
```

## 2. Template `techspec.md`

````markdown
# TechSpec — [Funcionalidade]

## Resumo Executivo
[Visão técnica da solução: decisões arquiteturais principais + estratégia, 1-2 parágrafos.]

## Arquitetura do Sistema

### Visão Geral dos Componentes
[Componentes e responsabilidades — listar CADA componente novo ou modificado; relacionamentos; fluxo de dados.]

## Design de Implementação

### Interfaces Principais
[Interfaces de serviço principais, ≤20 linhas por exemplo:]
```
type NomeServico interface {
    NomeMetodo(ctx, entrada) (saida, erro)
}
```

### Modelos de Dados
[Entidades de domínio; tipos de requisição/resposta; esquemas de banco, se aplicável.]

### Endpoints de API
[Método e caminho (ex.: `POST /api/v0/recurso`); descrição; formatos de req/resp.]

## Pontos de Integração
[Só se houver integração externa: serviços/APIs, autenticação, tratamento de erros.]

## Abordagem de Testes

### Testes de Unidade
[Componentes a testar; mocks (apenas serviços externos); cenários críticos.]

### Testes de Integração
[Se necessário: componentes testados juntos; dados de teste.]

### Testes de E2E
[Se necessário: frontend junto com backend, usando Playwright.]

## Sequenciamento de Desenvolvimento

### Ordem de Construção
[1. Primeiro componente (por quê); 2. dependências; 3. subsequentes; 4. integração e testes.]

### Dependências Técnicas
[Bloqueantes: infraestrutura requerida, serviços externos.]

## Monitoramento e Observabilidade
[Métricas a expor, logs principais e níveis, integração com dashboards existentes.]

## Considerações Técnicas

### Decisões Principais
[Escolha + justificativa; trade-offs; alternativas rejeitadas e por quê.]

### Riscos Conhecidos
[Desafios potenciais; mitigação; áreas precisando pesquisa.]

### Conformidade com Skills Padrões
[Se o projeto tem .claude/skills/, liste as aplicáveis a esta techspec.]

### Arquivos relevantes e dependentes
[Arquivos relevantes e dependentes.]
````

## 3. Template `tasks.md`

```markdown
# Resumo de Tarefas de Implementação de [Funcionalidade]

## Tarefas

- [ ] 1.0 Título da Tarefa
- [ ] 2.0 Título da Tarefa
```

## 4. Template `NN_task.md`

```markdown
# Tarefa X.0: [Título da Tarefa]

<critical>Ler prd.md e techspec.md desta pasta (raiz da SPEC); sem essa leitura a tarefa é invalidada</critical>

## Visão Geral
[Breve descrição da tarefa.]

<skills>
### Conformidade com Skills Padrões
[Se o projeto tem .claude/skills/, liste as aplicáveis a esta tarefa.]
</skills>

<requirements>
[Requisitos obrigatórios — referencie os RF-n cobertos.]
</requirements>

## Subtarefas
- [ ] X.1 [Descrição da subtarefa]
- [ ] X.2 [Descrição da subtarefa]

## Detalhes de Implementação
[Referencie techspec.md — não repita a implementação.]

## Critérios de Sucesso
- [Resultados mensuráveis; requisitos de qualidade.]

## Testes da Tarefa
- [ ] Testes de unidade
- [ ] Testes de integração
- [ ] Testes E2E (se aplicável)

<critical>SEMPRE CRIE E EXECUTE OS TESTES DA TAREFA ANTES DE CONSIDERÁ-LA FINALIZADA</critical>

## Arquivos relevantes
- [Arquivos relevantes desta tarefa.]
```

**Checkboxes de task no formato R.6:** ao concluir, TODO checkbox de `tasks.md` e `NN_task.md` (tarefas, subtarefas, testes) é marcado como `- [x] X.1 Descrição (YYYY-MM-DD HH:MM, commit `hash`)`. Checkbox `[x]` sem timestamp = ERRO no lint. Altitudes de progresso sem sobreposição: task fecha em `tasks.md`, fase fecha no SNAPSHOT, critério fecha no `main.md`.

## 5. QA / review / bugfix

| Artefato | O quê |
|---|---|
| `bugs.md` | bugs de QA: severidade (Alta/Média/Baixa), evidência, status da correção — contrato append-only em rules/interop.md |
| `qa-report.md` · `review-report.md` · `bugfix-report.md` | relatórios de pipeline (gerados pelas skills executar-qa/review/bugfix) |
| `evidence/` | evidência PERSISTENTE citada em relatório/critério (nome determinístico) |
| `intake/` | artefatos importados ORIGINAIS, verbatim (nunca reescritos; re-importações versionadas: `intake/prd-v2.md`) |
| `tmp/` | temporários — gitignored (R.12); evidência bruta nasce aqui |

Todo artefato de pipeline DEVE ter contrapartida no journal (`[nota]/[decisão]/[descoberta]` — R.6.1); `specctl audit` avisa artefato sem contrapartida.
