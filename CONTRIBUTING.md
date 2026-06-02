# Contributing

This repository is a public portfolio/demo project. Contributions are welcome when they improve the demo safely and keep the repo easy to run from a clean clone.

## Good contribution scope

- Documentation fixes and setup clarifications.
- Reliability fixes for local development, Docker, CI, and tests.
- UI polish or small product improvements that fit the existing demo scope.
- Bug fixes that do not require private infrastructure, production data, or client-specific logic.

## Out of scope

- Production support requests.
- Client-specific workflows or private business rules.
- Features that require real user data, paid infrastructure, or non-demo credentials.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
Copy-Item .env.example .env
alembic upgrade head
```

If you work with Docker instead, use:

```powershell
docker compose up --build
```

## Before opening a PR

Run the same checks enforced by CI:

```powershell
ruff check .
pytest
python -c "from app.api.main import app; print(app.title)"
python -m pip wheel . --no-deps
docker build -t manager-bot-local-check .
```

## Security and secrets

- Never commit `.env`, API keys, webhook secrets, or local database artifacts.
- Keep `.env.example` placeholder-only.
- Do not paste real secrets into issues, PRs, screenshots, CI logs, or release notes.

## PR expectations

- Keep changes focused.
- Update docs when setup or behavior changes.
- Explain what changed, why it changed, and how you validated it.
