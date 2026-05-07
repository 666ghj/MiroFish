# Contributing to MiroFish

Thank you for your interest in contributing to MiroFish. We welcome bug reports, feature ideas, documentation improvements, and code contributions from the community. Please review the project overview and setup details in [README.md](./README.md) before you start. A Simplified Chinese version of this guide is available at [CONTRIBUTING-ZH.md](./CONTRIBUTING-ZH.md).

## Code of Conduct

Please be respectful, constructive, and inclusive in all interactions. We value collaboration, clear communication, and helpful feedback across issues, discussions, and Pull Requests.

## How to Report Bugs

1. Search existing Issues first to avoid duplicates.
2. Open a new report in the [GitHub Issues](https://github.com/666ghj/MiroFish/issues) tab.
3. Include the following details:
   - Operating system and version
   - Python version
   - Node.js version
   - Steps to reproduce the problem
   - Full error traceback or logs
   - LLM provider and model name in use (this is a common source of issues in this repo)

## How to Suggest Features

1. Open a GitHub Issue and add the label `enhancement`.
2. Describe the use case and problem context, not just the proposed feature.
3. Check open Pull Requests first, since development moves quickly and your idea may already be in progress.

## Development Setup

```bash
# 1. Fork and clone
git clone https://github.com/YOUR_USERNAME/MiroFish.git
cd MiroFish

# 2. Copy env file and fill in your API keys
cp .env.example .env
# Required: LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME, ZEP_API_KEY

# 3. Install all dependencies (Node + Python via uv)
npm run setup:all

# 4. Start development servers
npm run dev
# Frontend: http://localhost:3000
# Backend:  http://localhost:5001
```

`npm run setup:all` installs frontend and root Node.js dependencies, then creates and prepares the Python virtual environment using `uv`.

## Project Structure

- `backend/` — Python FastAPI backend, simulation engine, LLM client, and graph builder
- `frontend/` — Vue.js frontend
- `locales/` — i18n translation files
- `.env.example` — all configurable environment variables

## Making a Pull Request

1. Start from the latest `main` branch.
2. Create a focused branch using one of these naming patterns:
   - `feat/your-feature`
   - `fix/your-fix`
   - `docs/your-docs`
3. Keep each Pull Request focused on one concern.
4. Fill out the PR description clearly:
   - What changed
   - Why it changed
5. Reference related Issues when applicable, for example: `Closes #123`.
6. Before submitting, make sure `npm run dev` starts successfully without errors.

## Commit Message Convention

Use Conventional Commits:

- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation only
- `chore:` tooling/config
- `refactor:` code restructure without behavior change

Example:

`feat(graph_builder): add retry mechanism for Zep connection failures`

## LLM Compatibility Notes

- The backend supports any OpenAI-compatible LLM API.
- Recommended default for cost-effectiveness: Alibaba Qwen-plus via Bailian Platform.
- If you contribute LLM-related changes, test with at least one local or cloud model.
- Do not hardcode model names; always use the `LLM_MODEL_NAME` environment variable.

## Questions?

- GitHub Discussions: <https://github.com/666ghj/MiroFish/discussions>
- Discord: <http://discord.gg/ePf5aPaHnA>
- Email: <mailto:mirofish@shanda.com>
