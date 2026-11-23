# Diagnóstico técnico — MiroFish (fork aliothbl/mirofish)

- **Data:** 2026-11-23
- **Commit analisado:** `7657031` (main)
- **Escopo:** Etapa 1 do plano (análise somente leitura). Nenhum arquivo versionado foi alterado.
- **Método:** leitura do código em três frentes paralelas (arquitetura/segurança, qualidade/testes, performance/uso de LLM) e execução dos testes que rodam offline.
- **Referências:** `arquivo:linha` apontam para o commit acima.

---

## 1. Resumo executivo

O MiroFish é um pipeline de 5 etapas:

1. documento → ontologia
2. grafo de conhecimento (Zep Cloud) → personas
3. simulação social multiagente (OASIS/camel-ai)
4. relatório por agente ReAct
5. chat com os agentes

O tamanho é de cerca de 30 mil linhas no backend (Python/Flask) e 18 mil no frontend (Vue 3).

**Pontos fortes:**
- A integração com o Zep é cuidadosa e testada: ingestão *fail-closed*, retry com `Retry-After`, paginação e locks por grafo.
- O tratamento de uploads é razoável: extensões permitidas, limite de 50 MB e nomes aleatórios.
- Os subprocessos são iniciados com segurança.
- As dependências estão travadas em `uv.lock`.

**Fragilidades principais:**
1. **Segurança da execução local.** Não há autenticação, o servidor escuta em `0.0.0.0` e o CORS aceita `*`. Qualquer site ou máquina da rede pode acionar a API e gastar créditos. Há ainda XSS armazenado via saída do LLM e tracebacks devolvidos ao cliente.
2. **Manutenibilidade.** Há arquivos-deus de 2–5 mil linhas, três cópias quase idênticas do script de simulação e quatro cópias do protocolo de IPC.
3. **Confiabilidade.** O estado crítico fica só em memória, as escritas de JSON não são atômicas e o CI não roda nenhum teste do backend.
4. **Modelos locais.** Não dá para escolher o modelo por etapa. Na simulação, a memória dos agentes e o loop de ferramentas não têm limite, o que é incompatível com contexto curto.

**Conclusão:** antes de experimentar modelos locais, vale fazer quatro coisas, nesta ordem: (a) fechar a exposição de rede; (b) pôr os testes do backend no CI; (c) instrumentar as chamadas de LLM; (d) permitir um modelo por etapa.

---

## 2. Arquitetura

### 2.1 Stack e versões (resolvidas em `uv.lock` / `package.json`)

| Camada | Tecnologia |
|---|---|
| Backend | Python ≥3.11,<3.13 · Flask 3.1.2 (servidor de desenvolvimento Werkzeug) · flask-cors 6.0.2 · openai 1.109.1 · pydantic 2.12 · PyMuPDF 1.26 |
| Simulação | camel-oasis 0.2.5 · camel-ai 0.2.78, que puxam torch 2.9.1 e transformers 4.57 (imagem pesada) |
| Memória/grafo | zep-cloud 3.25.0 (SaaS; self-hosted é bloqueado em `config.py:70`) |
| Frontend | Vue 3.5 · Vite 7.3 · vue-router 4.6 · vue-i18n 11.3 · axios 1.18 · d3 7.9 |
| Orquestração dev | `concurrently` (raiz) · uv · Docker de estágio único |
| Persistência | Arquivos em `backend/uploads/` (JSON, JSONL, MD) e SQLite do OASIS. Não há banco de aplicação. |

### 2.2 Mapa de módulos

**API (Flask)**
- `api/graph.py`: projetos, upload e ontologia, construção do grafo.
- `api/simulation.py`: 2.878 linhas e 31 rotas (preparação, execução, entrevistas).
- `api/report.py`: geração do relatório, streaming de logs e chat.

**Services**
- `ontology_generator`, `text_processor`, `graph_builder`, `zep_entity_reader`.
- `oasis_profile_generator`: gera as personas.
- `simulation_config_generator`.
- `simulation_manager`: estado da simulação.
- `simulation_runner`: subprocesso e monitoramento.
- `simulation_ipc`: IPC por arquivos.
- `zep_graph_memory_updater`.
- `zep_tools`: ferramentas do agente de relatório.
- `report_agent`: ReAct com `<tool_call>` em texto.

**Models**
- `project.py`: projetos em arquivos JSON.
- `task.py`: registro de tarefas em memória (singleton).

**Utils**
- `llm_client`: cliente OpenAI com modo JSON e fallback.
- `zep`, `zep_paging`, `zep_lifecycle`, `file_parser`, `logger`, `locale`.

**Scripts**
- `run_{twitter,reddit,parallel}_simulation.py`: rodam o OASIS num subprocesso.

**Frontend**
- Fluxo de views: Home → MainView → Simulation → SimulationRun → Report → Interaction.
- Um componente `Step1..5*.vue` por etapa.
- `GraphPanel`: visualização do grafo com d3.

### 2.3 Fluxos principais

```
1 Grafo     POST /api/graph/ontology/generate ─► parse doc ─► LLM (síncrono, na requisição)
            POST /api/graph/build ─► Thread ─► chunks 500 chars ─► Zep batch ─► polling 3 s
2 Ambiente  POST /api/simulation/create|prepare ─► Thread ─► Zep entidades
            ─► LLM personas (ThreadPool 5) ─► LLM config ─► profiles.json/csv + config.json
3 Simulação POST /start ─► Popen(scripts/run_*.py) ─► OASIS + camel (tool calling, semáforo 30)
            ─► actions.jsonl / *.db ─► thread monitora a cada 2 s ─► run_state.json + Zep updater
4 Relatório POST /api/report/generate ─► Thread ─► outline (LLM) ─► por seção: ReAct ≤5 iterações
            com ferramentas Zep e entrevistas via IPC ─► section_NN.md, full_report.md
5 Interação POST /api/report/chat (ReAct curto) · POST /simulation/interview* ─► IPC por arquivo
```

**Estado em memória:** `TaskManager`, os processos do runner, os locks de grafo e o cache do `SimulationManager`.
- Um restart do backend perde o status das tarefas, mas os subprocessos da simulação continuam rodando.
- Por isso o backend só funciona com um único processo.

### 2.4 Acoplamento

- Não há import circular em nível de módulo. Dois ciclos são quebrados com import dentro de função (`simulation_runner.py:257`, `zep_tools.py:1305`).
- `api/graph.py:40-73` acessa atributos internos do `SimulationRunner`.
- As APIs chamam métodos privados dos managers (`_get_simulation_dir`, `_save_simulation_state`, `_get_report_markdown_path`).
- O caminho do diretório da simulação é montado à mão em vários pontos.
- O SDK do Zep é usado diretamente em 7 módulos, sem uma interface `GraphStore`. Por isso, trocar o Zep exige refatoração prévia.

### 2.5 Configuração

- `.env` na raiz é carregado com `override=True` (`config.py:10-15`): o arquivo **vence** as variáveis de ambiente reais.
- `run.py:27-33` aborta se faltar `LLM_API_KEY` ou `ZEP_API_KEY`.
- **Armadilha do boost:** o `.env.example` traz `LLM_BOOST_*` com placeholders. Copiar o arquivo sem editar liga o boost com credenciais inválidas, e a metade Reddit da simulação paralela falha.
- O boost só é usado na metade Reddit (`run_parallel_simulation.py:1322`).
- A seleção do modelo passa por `os.environ` global (`:1022-1030`).

---

## 3. Segurança

| Sev. | Achado | Evidência |
|---|---|---|
| **Alta** | Nenhuma autenticação. Backend em `0.0.0.0:5001`, Vite com `--host`, Docker publica 3000/5001 | `run.py:39`, `frontend/package.json`, `docker-compose.yml` |
| **Alta** | CORS `origins: "*"`. Qualquer site aberto no navegador pode acionar o backend local e gastar créditos de LLM/Zep | `app/__init__.py:39` |
| Média | XSS armazenado. Markdown convertido por regex, sem escape, para `v-html`/`innerHTML`. Prompt injection num documento enviado pode virar script no relatório | `Step4Report.vue:1874`, `Step5Interaction.vue:557` |
| Média | 52 handlers devolvem `traceback.format_exc()` ao cliente | `api/simulation.py` (30), `api/report.py` (17), `api/graph.py` (5) |
| Média | IDs vindos do corpo JSON não são validados antes de `os.path.join`. `_get_simulation_dir` faz `makedirs` de qualquer ID | `simulation_manager.py:152-156` |
| Média | Servidores de desenvolvimento em "produção": o Docker roda `npm run dev` + Flask dev | `Dockerfile`, `run.py:46` |
| Baixa | Corpo de toda requisição JSON é logado em DEBUG e gravado em `backend/logs/` | `app/__init__.py:58-59`, `logger.py:74` |
| Baixa | O subprocesso herda o ambiente inteiro, incluindo as chaves. `SECRET_KEY` padrão hard-coded (não é usada) | `simulation_runner.py:517-549`, `config.py` |

**Sem problemas:** não há `eval`, `exec`, `pickle`, `yaml.load` nem `os.system`. O SQL é parametrizado. O download de scripts usa lista de permitidos. O `.env` é ignorado pelo Git e pelo Docker.

---

## 4. Qualidade e manutenção

### 4.1 Arquivos e funções grandes

| Arquivo | Linhas | Destaques |
|---|---|---|
| `frontend/src/components/Step4Report.vue` | 5.162 | ~2.950 linhas são CSS |
| `backend/app/api/simulation.py` | 2.878 | `prepare_simulation` 285 l., `start_simulation` 284 l. |
| `backend/app/services/report_agent.py` | 2.619 | `ReportAgent` (1.058 l.) e `ReportManager` (689 l.) no mesmo arquivo |
| `backend/app/services/simulation_runner.py` | 2.033 | classe-deus de 1.830 linhas |
| `backend/app/services/zep_tools.py` | 1.734 | `ZepToolsService` com 1.329 linhas |
| `backend/app/api/graph.py` | 963 | `_build_graph_impl`, com 380 linhas, é a maior função do repo |

A orquestração (threads, estado, *leases*) fica dentro dos handlers HTTP.

### 4.2 Duplicação

- **Scripts de simulação:** `run_twitter_simulation.py` e `run_reddit_simulation.py` são cerca de 95% idênticos. O `run_parallel_simulation.py` compartilha ~480 linhas com cada um.
- **Protocolo de IPC em 4 cópias:** `simulation_ipc.py` e os 3 scripts. O `SimulationIPCServer` é exportado mas nunca usado.
- **Frontend:** as views repetem de 270 a 344 linhas entre si. Helpers como `addLog` e `stopPolling` são redefinidos em 5 a 9 arquivos. 39 classes CSS se repetem em 3 ou mais componentes, e não há folha de estilo compartilhada.

### 4.3 Código morto ou obsoleto

- `frontend/src/views/Process.vue`: 2.076 linhas, não é importado por ninguém. A rota `Process` usa `MainView.vue`.
- `backend/app/utils/retry.py`: nenhum import. O retry real fica em `zep.py` e `llm_client.py`.
- `SimulationIPCServer` e partes de `scripts/action_logger.py`.
- `backend/scripts/test_profile_format.py`: script ad-hoc que o pytest provavelmente coleta.
- `run_parallel_simulation.py:45-60` faz monkey-patch global de `builtins.open`.

### 4.4 Erros, logs e i18n

- **Captura de exceções:** 4 `except:` sem tipo e 170 `except Exception`, dos quais ~40 terminam em `pass`.
- **Formato de erro inconsistente:** a chave varia entre `error` (182 ocorrências) e `message` (26). Não há um error handler central.
- **Logs:** o app usa `get_logger` de forma consistente, mas os scripts usam `print`. Importar o logger cria `backend/logs/` dentro do repo, inclusive nos testes.
- **Idioma:** cerca de 3.400 linhas do backend e ~280 do frontend estão em chinês, mesmo com o vue-i18n instalado.
- **Risco silencioso:** `Step4Report.vue:557-567` faz parse da saída do backend com regex em chinês (`/分析问题:/`). Traduzir os prompts quebra a tela sem nenhum erro.

---

## 5. Testes e confiabilidade

**Inventário:**
- `backend/tests` tem 18 arquivos e cerca de 110 testes pytest. São unitários e de contrato, quase todos sobre o Zep e o `llm_client`, e nenhum chama API real.
- `tests/` (na raiz) tem 28 testes `unittest` dos scripts de star-history.

**Execução:**
- **Raiz:** 28 testes passaram em 1,3 s.
- **Backend: não executado.** O `.venv` ficou vazio após a instalação interrompida, e o `uv sync` precisa baixar 149 pacotes. O Python do sistema é 3.10. **O status atual da suíte do backend é desconhecido.**

**Cobertura:** cerca de 8 das 59 rotas têm teste. Sem nenhum teste:
- a preparação da simulação e as entrevistas;
- o loop ReAct do relatório e o chat;
- `SimulationRunner._monitor_simulation`, o spawn e o stop do subprocesso;
- o IPC de ponta a ponta e os scripts OASIS;
- `simulation_config_generator`, `file_parser`, `text_processor`;
- todo o frontend.

**Ferramentas:**
- Não há ruff/flake8/black, mypy, configuração do pytest, `conftest.py` nem pre-commit.
- No frontend não há ESLint, Prettier, Vitest nem checagem de tipos.

**CI:**
- `docker-image.yml` só constrói a imagem, em tags.
- `update-star-history.yml` só roda os testes de star-history.
- **Nenhum PR ou push roda os testes do backend nem o build do frontend.**

---

## 6. Performance, escalabilidade e uso de LLM

### 6.1 Perfil de chamadas de LLM por etapa

N = número de agentes ou entidades, R = número de rodadas, Aᵣ = agentes ativos na rodada r.

| Etapa | Chamadas | Tamanho (estimado) | Concorrência | Recursos exigidos | Modelo local 7–8B |
|---|---|---|---|---|---|
| Ontologia | 1 (+1 retry) | entrada de até **50k chars** (~15–40k tokens) | serial | `json_object`, contexto longo | **Ruim**: manter na API |
| Ingestão no grafo | 0 (a extração roda no servidor do Zep) | — | — | — | n/a |
| Personas | N × (1–3) + 2 buscas no Zep por entidade | 1–4k tokens de entrada, até 2,5k de saída | ThreadPool 5 | `json_object`; **cai em perfil baseado em regras sem avisar** | **Boa/média**: principal candidata |
| Configuração da simulação | 2 + ⌈N/15⌉ | saída com JSON de 15 agentes, ~3–5k tokens | serial | `json_object` | Média: risco de truncamento |
| Simulação (OASIS) | Σ Aᵣ × **≥2** por plataforma (×2 no modo paralelo); padrão de até 144 rodadas | ≥3–5k tokens, **crescendo a cada rodada** | `gather`, semáforo 30 | **tool calling nativo** | Viável só com limites (ver 6.2) |
| Relatório | ~20–45 | 10–30k tokens | seções em série | `<tool_call>` em texto, contexto longo | **Ruim/média**: manter na API |
| Chat | ≤3 por mensagem | moderado | por requisição | `<tool_call>` em texto | Média |

**Não existe escolha de modelo por etapa:** tudo usa `LLM_*`. A única divisão existente é a metade Reddit da simulação paralela no boost.

### 6.2 Riscos de compatibilidade com Ollama

1. **Loop de ferramentas sem limite.** O camel usa `max_iteration=None`. Um modelo fraco que continua emitindo chamadas de ferramenta nunca termina. Só modelos com suporte a *tools* funcionam (Qwen2.5/3, Llama 3.1). **O `llama3` instalado no notebook não tem esse suporte.**
2. **Memória do agente sem teto.** Com nome de modelo fora da lista da OpenAI, o limite vira `token_limit=999_999_999`, e o aviso disso é filtrado pelos scripts. Quando o prompt passa de `num_ctx`, o Ollama trunca o início sem avisar, e o agente perde a persona.
3. **O OASIS carrega `twhin-bert-base` na GPU**, se o torch a enxergar. Ele disputa os 8 GB de VRAM com o LLM. Não está confirmado que o wheel do torch 2.9 ainda suporta Pascal (sm_61).
4. **Configuração via `os.environ` global.** Se `LLM_BOOST_BASE_URL` estiver vazio, o Reddit herda a URL principal sem avisar.
5. **Modelos com raciocínio** (qwen3, deepseek-r1): as tags `<think>` só são removidas no caminho do `LLMClient`. Os geradores de persona e de configuração usam o cliente cru, e o JSON deles pode quebrar.

### 6.3 Gargalos

| Sev. | Problema | Evidência |
|---|---|---|
| Alta | Contexto e latência crescem com R (memória sem limite + loop sem teto) | camel, ver 6.2 |
| Alta | `run-status/detail`, consultado a cada 3 s, relê `actions.jsonl` inteiro 3× por requisição e devolve tudo, sem paginação | `api/simulation.py:1977-1988`, `simulation_runner.py:1156` |
| Alta | Estado só em memória e sem lock (`_run_states`). Perdido no restart; só funciona com um processo | `models/task.py:62-73`, `simulation_runner.py:228` |
| Média | Escritas de JSON não atômicas, lidas em paralelo pela API (`run_state.json` a cada 2 s) | `simulation_runner.py:357-366` |
| Média | Arquivo de personas reescrito inteiro a cada perfil gerado, I/O O(N²) | `oasis_profile_generator.py:940-960` |
| Média | IPC por arquivo com polling; timeout de entrevista de 180 s, apertado para GPU local | `simulation_ipc.py:157-176`, `zep_tools.py:1381` |
| Média | Zep: barreira faz 1 GET por episódio a cada 3 s; `insight_forge` faz N+1 chamadas sem teto; o frontend rebaixa o grafo inteiro a cada 10–30 s | `zep_graph_memory_updater.py:599`, `zep_tools.py:1027`, `MainView.vue:309` |

---

## 7. Dívidas técnicas (resumo)

1. Três scripts de simulação e quatro cópias do protocolo IPC.
2. Arquivos-deus no backend e no frontend.
3. Estado crítico em memória e escritas não atômicas.
4. Ausência de abstração sobre o Zep (trava em fornecedor SaaS).
5. Sem formato de erro padrão; tracebacks expostos ao cliente.
6. Código morto (`Process.vue`, `retry.py`, `SimulationIPCServer`).
7. Mistura de idiomas e regex em chinês acoplando frontend e backend.
8. Nenhuma ferramenta de qualidade e nenhum teste no CI.
9. Docker em modo de desenvolvimento, como root, com tag `latest` mutável.
10. Dependências dev declaradas duas vezes; `requirements.txt` redundante com o `pyproject.toml`.

---

## 8. Backlog priorizado

**Legenda:**
- **Imp/Esf/Risco:** A = alto, M = médio, B = baixo.
- **Urg** = urgência.
- **Dep** = item do qual depende.
- Cada item vira uma SPEC no sistema SDD v4 antes de ser implementado.

### P0 — Correções críticas (antes de rodar com chaves reais)

| # | Item | Imp | Esf | Risco | Urg | Dep | Critério verificável |
|---|---|---|---|---|---|---|---|
| 1 | Bind padrão `127.0.0.1` (backend e Vite) e CORS restrito à origem do frontend | A | B | B | A | — | `ss -ltn` mostra só 127.0.0.1; requisição com `Origin` estranho é rejeitada |
| 2 | Corrigir o `.env.example` (boost comentado) e avisar no startup se o boost tiver placeholder | M | B | B | A | — | `.env` copiado sem edição roda o modo paralelo sem erro de auth |
| 3 | Escapar HTML na renderização de markdown (sanitizador) | A | B | B | M | — | Relatório com `<img onerror>` injetado não executa script |
| 4 | Remover `traceback` das respostas, com error handler central | M | M | B | M | 6 | Nenhuma resposta 5xx contém stack trace; teste cobre |
| 5 | Validar formato dos IDs antes de montar caminhos | M | B | B | M | — | ID com `../` retorna 400; teste cobre |

### P1 — Base para evoluir com segurança

| # | Item | Imp | Esf | Risco | Urg | Dep | Critério |
|---|---|---|---|---|---|---|---|
| 6 | Rodar a suíte do backend localmente e no CI (workflow pytest + `vite build`), com config do pytest e logger sem efeito colateral | A | B | B | A | — | Workflow verde em PR; baseline registrado |
| 7 | ruff (lint + format) no backend e ESLint no frontend, sem reformatar tudo de uma vez | M | B | B | M | 6 | CI falha em violação nova |
| 8 | Instrumentar chamadas de LLM: etapa, modelo, tokens, latência, erros, fallbacks | A | M | B | A | — | Log JSONL por execução com os campos acima |
| 9 | Modelo por etapa (`LLM_<ETAPA>_*` com fallback para `LLM_*`), sem `os.environ` global | A | M | M | A | 6, 8 | Personas no Ollama e o resto na API, num mesmo run |
| 10 | Limites para modelo local: `max_iteration` do camel, `token_limit` da memória, `num_ctx`, timeout de entrevista configurável | A | M | M | A | 9 | Simulação de 10 agentes × 6 rodadas termina com contexto < `num_ctx` |
| 11 | Expor o fallback de personas por regras como métrica e aviso, em vez de silencioso | M | B | B | M | 8 | Contagem de fallbacks aparece no status e no log |

### P2 — Arquitetura e performance

| # | Item | Imp | Esf | Risco | Dep |
|---|---|---|---|---|---|
| 12 | Unificar os scripts de simulação e o protocolo IPC num módulo único | A | A | M | 6 |
| 13 | Paginar ou incrementar `run-status/detail` (offset no JSONL) | A | M | B | 6 |
| 14 | Escritas atômicas (tmp + rename) em todos os JSON de estado | M | B | B | — |
| 15 | Persistir tarefas e estado do runner (arquivo ou SQLite) e recuperar após restart | M | M | M | 14 |
| 16 | Interface `GraphStore` sobre o Zep; avaliar Graphiti self-hosted ou um store local | A | A | A | 6 |
| 17 | Quebrar `api/simulation.py`, `report_agent.py` e `simulation_runner.py` em camadas | M | A | M | 6, 12 |
| 18 | Otimizar o Zep: barreira em lote, teto no `insight_forge`, grafo incremental no frontend | M | M | B | 16 (parcial) |

### P3 — Dívida e acabamento

| # | Item | Dep |
|---|---|---|
| 19 | Remover código morto (`Process.vue`, `retry.py`, `SimulationIPCServer`, partes do `action_logger`) | 6 |
| 20 | Frontend: composables (`usePolling`, `useLog`, `useGraph`) e CSS compartilhado | 7 |
| 21 | Contrato estruturado backend→frontend em vez das regex em chinês | 6 |
| 22 | Imagem Docker de produção (multi-stage, não root, build estático, gunicorn) | 1, 6 |
| 23 | i18n dos logs e mensagens do backend | 21 |

### Experimentação com IA (laboratório)

| # | Item | Dep |
|---|---|---|
| E1 | Inventário da máquina com a GTX 1070 e Ollama servindo na LAN, com acesso restrito ao notebook | script de inventário |
| E2 | Benchmark 1: personas API vs local (abaixo) | 8, 9 |
| E3 | Benchmark 2: simulação pequena com modelo local | 10 |
| E4 | Avaliar substituto local do Zep | 16 |

---

## 9. Benchmarks reproduzíveis propostos

1. **Personas, API vs local.**
   - Entrada: 20 entidades fixas (snapshot do grafo ou mocks), com a busca no Zep stubada.
   - Variações: paralelismo 1/2/5; modelo da API vs `qwen2.5:7b` e `llama3.1:8b` em Q4_K_M com `num_ctx=8192`.
   - Métricas: tempo, tokens/s, taxa de JSON válido, **fallbacks por regras**, tamanho da persona e nota cega de um modelo-juiz.
2. **Simulação pequena.**
   - Entrada: configuração fixa, 10 agentes, 6 rodadas, só Twitter, seed fixa.
   - Métricas: chamadas por ação, crescimento do prompt por rodada, latência p50/p95, tool calls inválidas, distribuição de ações no SQLite, VRAM de pico com e sem o twhin-bert na GPU.
3. **Teto de contexto.**
   - Entrada: ontologia e uma seção do relatório com entradas gravadas.
   - Variação: `num_ctx` de 4k, 8k, 16k e 32k.
   - Métricas: truncamento e validade do schema.
4. **Custo do Zep.**
   - Entrada: um run de ponta a ponta com 1 documento e 20 agentes.
   - Métricas: chamadas por fase, espera da ingestão, polls da barreira, N+1 do `insight_forge`, ocorrências de 429.
5. **Carga do backend.**
   - Entrada: `actions.jsonl` sintético com 1k, 10k e 50k linhas, consultado a cada 3 s por 1 a 3 abas.
   - Métricas: latência, tamanho da resposta, CPU e leituras parciais.

---

## 10. Viabilidade preliminar de modelos locais (GTX 1070)

**Status:** hipótese, a confirmar com o inventário real da máquina da GPU.

- **Capacidade:** com 8 GB de VRAM e arquitetura Pascal, cabem modelos de 7–8B em Q4/Q5 com contexto de 8–16k, a cerca de 20–40 tokens/s. Um 14B só roda com offload parcial para a CPU, mais lento.
- **Divisão sugerida:**
  - Modelo local: **personas** e, depois dos itens 9 e 10, a **simulação** com limites.
  - API: ontologia, configuração da simulação, relatório e chat.
- **Zep:** continua externo até o item 16 (a extração do grafo roda no servidor deles).
- **Notebook atual:** sem GPU e com 57 GB livres em disco. Serve só como cliente.

---

## 11. Limitações desta análise

- ~~A suíte do backend não foi executada.~~ Resolvido na seção 12.
- Tamanhos em tokens, número de chamadas do relatório e profundidade do loop de ferramentas são estimativas pela leitura do código, não medições.
- "Código não usado" foi identificado por grep e pode ignorar imports dinâmicos.
- O suporte do torch 2.9 a Pascal e o comportamento do `os.environ` com o boost não foram verificados.

---

## 12. Evidências coletadas após o diagnóstico (2026-11-23)

### 12.1 Baseline de testes

- `uv sync --frozen` levou 23 min na primeira vez (download de torch/CUDA), com Python 3.12 gerenciado pelo uv.
- `pytest tests` no backend: **129 passed em 10,3 s**, com 6 SyntaxWarnings vindos de dentro do `zep-cloud`. Esse é o piso para qualquer SPEC (P-4).

### 12.2 Primeira execução de ponta a ponta

- **Entrada:** briefing de lançamento do Lototec (3,3k caracteres), `gpt-4o-mini`, Zep Cloud, BOOST desligado, backend com `FLASK_HOST=127.0.0.1`.
- **Resultado da preparação:** 19 entidades viraram 19 personas. Parte delas são organizações genéricas ("Instagram", "YouTube", "Caixa").
- **Rodadas:** o processo subiu sem `--max-rounds` e usou o padrão de **144 rodadas** (144 h simuladas, 60 min por rodada). O campo de rodadas da UI não deixa isso evidente.
- **Estouro de contexto confirmado (§6.2, item 2):** a partir da rodada ~70 (13:30), chamadas falharam com `maximum context length is 128000 tokens` (129.452 solicitados). Os agentes afetados deixam de agir, e o custo por chamada cresce até o teto.
- **Desaceleração:** cada rodada passou de segundos para 1–2 min no Twitter e 3–4 min no Reddit perto da rodada 90.
- **Possível bug de exibição:** o log da UI mostra `T:0h` constante enquanto as rodadas avançam.
- **Erro de crédito mal sinalizado:** `RateLimitError 429` com `insufficient_quota` aparece na UI como falha genérica.

**Consequência para o backlog:** os itens 10 (limites de contexto e de rodadas) e 11 (sinalização de fallback e erros) sobem de prioridade, porque o problema se manifesta mesmo com a API e um modelo de 128k.
