# SPEC-20261123-1613: BOOST desligado por padrão e placeholder detectado

**Status:** draft
**Porte:** P
**Owner:** @aliothbl
**Criada:** 2026-11-23 16:13
**Ativada:** —
**Concluída:** —
**Pausada em:** —
**Commit final:** —
**Keywords:** env, boost, placeholder, configuracao
**Features:** infra, llm
**Branch:** —
**Programa:** —
**Workspace:** —
**Origem:** usuário em 2026-11-23 16:13 (backlog P0 item 2 de docs/DIAGNOSTICO-2026-11-23.md)
**Resumo:** Copiar `.env.example` sem edição não liga mais o BOOST com credenciais falsas, e um placeholder é detectado e avisado.

## Objetivo

O `.env.example` traz `LLM_BOOST_*` ativos com valores `your_..._here`, e `run_parallel_simulation.py:1002` considera o BOOST ligado sempre que `LLM_BOOST_API_KEY` não está vazio. Copiar o exemplo sem editar faz a metade Reddit da simulação falhar com erro de autenticação — o que aconteceu na primeira configuração local (2026-11-23). A SPEC elimina essa armadilha.

## Escopo

**DENTRO:**
- `.env.example`: linhas `LLM_BOOST_*` comentadas, com explicação do que o BOOST faz (só a metade Reddit da simulação paralela).
- Detecção de placeholder (`your_`, `_here`, vazio) em `LLM_API_KEY`, `ZEP_API_KEY` e `LLM_BOOST_*` no `Config.validate()`: erro para as obrigatórias, aviso e BOOST desligado para as opcionais.
- `create_model` só usa BOOST se `LLM_BOOST_API_KEY`, `LLM_BOOST_BASE_URL` e `LLM_BOOST_MODEL_NAME` estiverem preenchidos e não forem placeholders; caso contrário cai no LLM principal com log de aviso.

**FORA:**
- Roteamento de modelo por etapa (backlog item 9).
- Remoção do uso de `os.environ` global para o camel (item 9).

## Invariantes

- NUNCA uma configuração incompleta de BOOST faz a simulação falhar: na dúvida, usa o LLM principal.
- NUNCA o valor de uma chave aparece em log ou mensagem de erro.

## Implementação

Função utilitária `is_placeholder(value)` em `backend/app/config.py`, reaproveitada por `Config.validate()` e pelo script de simulação; o script já carrega o `.env` da raiz.

### Modelo de dados

—

## Riscos

- Heurística de placeholder com falso positivo numa chave real — mitigação: padrões restritos (`your_`, `_here`, `placeholder`) e teste unitário.

## Sinais de sucesso

- Quem copia o `.env.example` e preenche só `LLM_*` e `ZEP_API_KEY` roda a simulação paralela sem erro.

## Critério de aceite

- [ ] Com `.env` = `.env.example` + só `LLM_API_KEY`/`ZEP_API_KEY` reais, a simulação paralela roda as duas plataformas no LLM principal.
- [ ] Com `LLM_BOOST_API_KEY=your_api_key_here`, o backend loga aviso de BOOST ignorado, sem exibir o valor.
- [ ] Teste unitário cobre `is_placeholder` e a escolha de modelo em `create_model`.
- [ ] Suíte do backend verde.
