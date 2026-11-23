# TAXONOMY.md — vocabulário canônico de áreas

> Orçamento-alvo: ≤1.600 bytes. Toda feature de `docs/features/` DEVE corresponder a uma área daqui (R.4).
> Área nova = confirmação explícita do usuário (R.13). Namespaces com `/` (ex.: `api/auth`).
> Formato por linha: `- <area> — definição 1 linha (aliases proibidos: x→area)`

## Áreas

- grafo — upload, ontologia, construção e leitura do grafo no Zep (aliases proibidos: ontologia→grafo, zep→grafo)
- ambiente — entidades, geração de personas e config da simulação (aliases proibidos: personas→ambiente, profiles→ambiente)
- simulacao — runner, scripts OASIS, IPC e memória da simulação no grafo (aliases proibidos: oasis→simulacao, runner→simulacao)
- relatorio — ReportAgent, ferramentas Zep do relatório e chat/entrevistas (aliases proibidos: report→relatorio, chat→relatorio)
- llm — cliente LLM, roteamento de modelo por etapa, compat OpenAI/Ollama (aliases proibidos: boost→llm, modelo→llm)
- web — frontend Vue: views, Step*, GraphPanel, i18n (aliases proibidos: frontend→web, ui→web)
- infra — config/env, run.py, Docker, CI, segurança de rede e qualidade (aliases proibidos: ci→infra, docker→infra)
- lab — experimentos de IA, benchmarks e modelos locais na GTX 1070 (aliases proibidos: benchmark→lab, ollama→lab)
