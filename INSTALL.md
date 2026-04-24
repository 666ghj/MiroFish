# MiroFish — Guia d'instal·lació i desplegament

Aquesta guia cobreix les dues modalitats d'execució:

- [Desenvolupament local](#1-desenvolupament-local) — frontend + backend en mode dev
- [Desplegament a Azure](#2-desplegament-a-azure-container-apps) — producció amb Docker i Azure Container Apps

---

## 1. Desenvolupament local

### Prerequisits

| Eina | Versió | Comprovació |
|---|---|---|
| **Node.js** | ≥ 18 | `node -v` |
| **Python** | ≥ 3.11, ≤ 3.12 | `python --version` |
| **uv** | última | `uv --version` |

### Instal·lació

```bash
# 1. Clonar el repositori
git clone https://github.com/jaumemir/MiroFish.git
cd MiroFish

# 2. Configurar variables d'entorn
cp .env.example .env
# Edita .env i omple els valors (vegeu la secció de variables)

# 3. Instal·lar totes les dependències (Node + Python)
npm run setup:all
```

### Variables d'entorn (`.env`)

```env
# ── LLM principal (OpenAI-compatible) ─────────────────────────────
LLM_API_KEY=la-teva-clau
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus

# ── Zep Cloud (graf de memòria) ───────────────────────────────────
ZEP_API_KEY=la-teva-clau-zep

# ── LLM accelerador (opcional) ────────────────────────────────────
LLM_BOOST_API_KEY=
LLM_BOOST_BASE_URL=
LLM_BOOST_MODEL_NAME=

# ── Autenticació ──────────────────────────────────────────────────
# Contrasenya de l'usuari "demo" per accedir a l'app
DEMO_PASSWORD=una-contrasenya-segura

# Clau per signar tokens JWT
# Genera-la amb: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=una-clau-secreta-llarga
```

### Execució

```bash
npm run dev
```

Obre el navegador a `http://localhost:3000`.  
Fes login amb usuari `demo` i la `DEMO_PASSWORD` que has configurat.

> El frontend (port 3000) i el backend (port 5001) s'inicien simultàniament.  
> Vite proxia automàticament les peticions `/api/*` al backend.

---

## 2. Desplegament a Azure Container Apps

### Prerequisits

| Eina | Versió | Instal·lació |
|---|---|---|
| **Azure CLI** | ≥ 2.60 | [docs.microsoft.com/cli/azure/install-azure-cli](https://docs.microsoft.com/cli/azure/install-azure-cli) |
| **Docker** | ≥ 24 | [docs.docker.com/get-docker](https://docs.docker.com/get-docker/) |
| **Python 3** | ≥ 3.8 | (per processar outputs JSON dels scripts) |

### Estructura dels fitxers de desplegament

```
azure/
├── config.sh.example   # plantilla de configuració (commited al repo)
├── config.sh           # valors reals amb secrets  (NO comitejar mai — gitignored)
├── infra.bicep         # infraestructura base: ACR + Log Analytics + Container Apps Env
├── container-app.bicep # Container App: es re-desplega a cada nova versió
├── 1-infra.sh          # script pas 1: crea la infraestructura (una sola vegada)
└── 2-build-deploy.sh   # script pas 2: build Docker + push + deploy (cada versió)
```

---

### Pas 0 — Login a Azure

```bash
az login
```

---

### Pas 1 — Configuració

```bash
cp azure/config.sh.example azure/config.sh
```

Edita `azure/config.sh` i omple **tots** els valors:

#### Variables obligatòries

| Variable | Descripció | On obtenir-la |
|---|---|---|
| `AZURE_SUBSCRIPTION_ID` | ID de la subscripció Azure | `az account show --query id -o tsv` |
| `AZURE_LOCATION` | Regió Azure (ex: `westeurope`) | [Llista de regions](https://azure.microsoft.com/regions/) |
| `DEMO_PASSWORD` | Contrasenya de l'usuari `demo` | Escull una contrasenya segura |
| `SECRET_KEY` | Clau Flask per signar JWT | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `LLM_API_KEY` | Clau de l'API LLM | [Alibaba Bailian](https://bailian.console.aliyun.com/) o OpenAI |
| `LLM_BASE_URL` | URL base de l'API LLM | Default: Alibaba Qwen |
| `LLM_MODEL_NAME` | Nom del model | Default: `qwen-plus` |
| `ZEP_API_KEY` | Clau de Zep Cloud | [app.getzep.com](https://app.getzep.com/) |

#### Variables opcionals

| Variable | Descripció | Default |
|---|---|---|
| `LLM_BOOST_API_KEY` | Clau LLM accelerador | (buit = desactivat) |
| `LLM_BOOST_BASE_URL` | URL LLM accelerador | (buit) |
| `LLM_BOOST_MODEL_NAME` | Model LLM accelerador | (buit) |
| `OASIS_DEFAULT_MAX_ROUNDS` | Rondes màximes simulació | `10` |
| `REPORT_AGENT_MAX_TOOL_CALLS` | Crides màximes a eines | `5` |
| `REPORT_AGENT_MAX_REFLECTION_ROUNDS` | Rondes de reflexió | `2` |
| `REPORT_AGENT_TEMPERATURE` | Temperatura del Report Agent | `0.5` |

> **Seguretat:** `azure/config.sh` està al `.gitignore`. Mai el comiteges al repositori.

---

### Pas 2 — Crear infraestructura (una sola vegada)

```bash
bash azure/1-infra.sh
```

Aquest script crea al resource group `rg_mirofish`:

| Recurs | Nom | Descripció |
|---|---|---|
| Resource Group | `rg_mirofish` | Contenidor de tots els recursos |
| Container Registry | `mirofsihacr` | Registre privat Docker (SKU Basic) |
| Log Analytics Workspace | `mirofish-logs` | Logs centralitzats (90 dies retenció) |
| Container Apps Environment | `mirofish-env` | Plataforma d'execució de contenidors |

Al final imprimeix l'ACR Login Server i l'ID de l'entorn. Guarda'ls si els necessites.

> **Idempotent:** pots executar-lo múltiples vegades sense errors.

---

### Pas 3 — Build i deploy (a cada nova versió)

```bash
bash azure/2-build-deploy.sh
```

El script fa automàticament:

1. Obté les dades de la infraestructura existent (ACR, Container Apps Env)
2. Genera un tag de versió amb format `<git-sha>-<timestamp>`
3. `docker build` de la imatge multi-stage (Vue build + Flask + gunicorn)
4. `docker push` a l'ACR privat
5. Desplega la Container App via Bicep amb tots els secrets configurats

Al final imprimeix la URL de l'aplicació:
```
URL de l'aplicació: https://mirofish.<hash>.westeurope.azurecontainerapps.io
```

---

### Gestió de versions i re-deploys

Cada execució de `2-build-deploy.sh` genera una nova revisió de la Container App amb tag únic. La versió `latest` sempre apunta a la darrera imatge.

Per veure l'historial de revisions:
```bash
az containerapp revision list \
  --name mirofish \
  --resource-group rg_mirofish \
  --output table
```

Per consultar els logs en temps real:
```bash
az containerapp logs show \
  --name mirofish \
  --resource-group rg_mirofish \
  --follow
```

---

### Arquitectura de producció

```
Internet
    │  HTTPS
    ▼
Container Apps Ingress (port 5001)
    │
    ▼
Flask + gunicorn (1 worker, 4 threads)
    ├── GET /              → serveix Vue SPA (frontend/dist/)
    ├── POST /api/auth/login  → autenticació JWT (pública)
    └── /api/*             → protegit per JWT Bearer token
```

**Escalat automàtic:** de 1 a 10 rèpliques per nombre de peticions concurrents (llindar: 20).

---

### Solució de problemes habituals

| Problema | Causa probable | Solució |
|---|---|---|
| `ERROR: No s'ha trobat azure/config.sh` | Fitxer no creat | `cp azure/config.sh.example azure/config.sh` |
| `Cannot login to ACR` | Docker no està en execució | `docker info` i arrenca Docker |
| Login retorna 401 sempre | `DEMO_PASSWORD` buida o incorrecta | Verifica el valor a `config.sh` / secret Azure |
| Container App no arrenca | Imatge no trobada a l'ACR | Verifica que `2-build-deploy.sh` hagi finalitzat sense errors |
| Token expirat al cap de 24h | Comportament esperat | Torna a fer login a `/login` |
