# ARCHITECTURE.md — mapa transversal região→feature

> Orçamento-alvo: ≤4.800 bytes. Nível 0.5 de leitura: responde "este trecho do código pertence a qual feature?".
> Detalhe e evidências (linhas, riscos, backlog): `docs/DIAGNOSTICO-2026-11-23.md`. Atualize quando uma SPEC mover fronteiras.

## Mapa região → feature

| Região (path) | Feature (TAXONOMY) | Nota (1 linha) |
|---|---|---|
| backend/app/api/graph.py, services/{ontology_generator,text_processor,graph_builder,zep_entity_reader}.py | grafo | ontologia via LLM síncrono; ingestão Zep batch, fail-closed |
| backend/app/utils/{zep,zep_paging,zep_lifecycle,file_parser,ontology}.py, models/project.py | grafo | cliente/retry/paginação Zep; locks por grafo; projetos em JSON |
| backend/app/services/{oasis_profile_generator,simulation_config_generator,simulation_manager}.py | ambiente | personas (ThreadPool 5) e config; fallback silencioso por regras |
| backend/app/api/simulation.py | ambiente · simulacao | 31 rotas, 2,9k linhas — preparo, start/stop, status, entrevistas |
| backend/app/services/{simulation_runner,simulation_ipc,zep_graph_memory_updater}.py | simulacao | Popen dos scripts; IPC por arquivos; ações → Zep em lotes de 5 |
| backend/scripts/run_{parallel,twitter,reddit}_simulation.py, scripts/action_logger.py | simulacao | OASIS+camel; ~95% duplicados entre si; protocolo IPC copiado |
| backend/app/api/report.py, services/{report_agent,zep_tools}.py | relatorio | ReAct com `<tool_call>` em texto; seções em série |
| backend/app/utils/{llm_client,openai_chat_compat}.py | llm | modelo único `LLM_*`; boost só no Reddit via os.environ |
| backend/app/models/task.py | infra | registro de tarefas em memória (perdido no restart) |
| backend/app/{__init__,config}.py, backend/run.py, utils/{logger,locale,retry}.py | infra | CORS *, bind 0.0.0.0, .env override; retry.py sem uso |
| frontend/src/views/*, components/Step{1..5}*.vue, components/GraphPanel.vue | web | uma view por etapa; Process.vue órfão |
| frontend/src/{api,router,i18n,store}/, locales/ | web | axios direto em :5001; vue-i18n en/zh |
| Dockerfile, docker-compose.yml, .github/workflows/, package.json | infra | imagem dev-mode; CI não roda testes do backend |
| backend/tests/, tests/ | infra | 129 testes backend (verdes em 7657031) + 28 de star-history |
| scripts/{star_history,fetch_star_count}.py, static/, .github/star-history/ | (sem feature) | utilidades do upstream (README) |
| scripts/specctl.mjs, docs/, .claude/ | (sem feature) | harness SDD v4 (vendorizado de soulradar/lototec) |

## Fluxos transversais

- Grafo: upload → `POST /api/graph/ontology/generate` (LLM na requisição) → `POST /api/graph/build` (thread) → chunks 500 chars → Zep batch → polling 3 s.
- Ambiente: `POST /api/simulation/prepare` (thread) → entidades Zep → personas LLM → config LLM → `uploads/simulations/<id>/`.
- Simulação: `POST /start` → subprocesso OASIS (tool calling, semáforo 30) → `actions.jsonl` → monitor 2 s → `run_state.json` + Zep updater. Memória do agente sem teto.
- Relatório: `POST /api/report/generate` (thread) → outline → ReAct por seção (Zep + entrevistas via IPC) → `uploads/reports/<id>/`.
- Laboratório (planejado): roteamento de modelo por etapa → Ollama na máquina da GTX 1070 via LAN.
