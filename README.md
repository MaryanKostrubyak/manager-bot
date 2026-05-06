# Finance Assistant Bot

<p align="center">
  <img src="docs/images/readme-hero.png" alt="Finance Assistant Bot portfolio demo cover" width="1000" />
</p>

<p align="center">
  <strong>Portfolio demo repository</strong> for a Telegram finance assistant with a FastAPI backend and responsive WebApp dashboard.
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-API-009688?style=flat-square&logo=fastapi&logoColor=white" />
  <img alt="Telegram" src="https://img.shields.io/badge/Telegram-Bot_+_WebApp-26A5E4?style=flat-square&logo=telegram&logoColor=white" />
  <img alt="SQLAlchemy" src="https://img.shields.io/badge/SQLAlchemy-Alembic-D71F00?style=flat-square" />
  <img alt="Docker" src="https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white" />
</p>

## Demo Positioning

This repository is intentionally shaped as a public portfolio/demo project. It shows the architecture, UX, API design, data modeling, and delivery quality behind a finance assistant MVP.

It is not a dump of private client production code. The public version uses demo-friendly configuration, seeded/local screenshots, placeholder environment values, and excludes real secrets, production data, deployment credentials, and client-specific business rules.

Good GitHub topics for this repository:

```text
portfolio, demo-project, telegram-bot, fastapi, finance-dashboard, webapp, sqlalchemy, docker
```

## Screenshots

<p align="center">
  <img src="docs/images/readme-dashboard.png" alt="Finance Assistant dashboard preview" width="1000" />
</p>

<p align="center">
  <img src="docs/images/readme-responsive.png" alt="Responsive Telegram WebApp preview" width="1000" />
</p>

<p align="center">
  <img src="docs/images/readme-demo-scope.png" alt="Portfolio demo scope and product flow" width="1000" />
</p>

## What It Demonstrates

- Telegram bot flows: onboarding, command handlers, inline menus, category actions, transaction parsing, and webhook processing.
- FastAPI backend: versioned REST routes, dependency wiring, healthcheck, analytics, budgets, exports, and Telegram integration endpoints.
- Data layer: async SQLAlchemy models, Alembic migrations, SQLite for local development, and Docker-ready PostgreSQL-style configuration.
- WebApp dashboard: responsive Telegram WebApp UI with KPI cards, charts, filters, budgets, savings goals, transaction history, settings, and assistant view.
- Import/export workflows: CSV/XLSX statement import, CSV exports, and receipt/assistant service boundaries.
- Delivery practices: Docker setup, environment-based settings, logging, migrations, tests, and clean repository hygiene.

## Feature Map

| Area | Demo capability |
| --- | --- |
| Bot | `/start`, quick actions, transaction parsing, reports, export entry points |
| API | Analytics, budgets, WebApp data, Telegram webhook, healthcheck |
| WebApp | Overview, operations, goals, history, AI assistant, settings |
| Data | Transactions, categories, budgets, user preferences, assistant feedback |
| Automation | Budget monitoring and reminder service structure |
| AI-ready services | Receipt extraction and assistant wrappers with optional OpenAI configuration |

## Tech Stack

| Layer | Tools |
| --- | --- |
| Bot | `python-telegram-bot`, Telegram Webhooks, Telegram WebApp |
| API | FastAPI, Pydantic, Uvicorn |
| Data | SQLAlchemy async, Alembic, SQLite/PostgreSQL-ready settings |
| Automation | APScheduler, optional Redis |
| WebApp | HTML, CSS, vanilla JavaScript, Chart.js |
| AI / Import | OpenAI SDK, Pandas, OpenPyXL |
| DevOps | Docker, docker-compose, Loguru, optional Sentry |
| Tests | Pytest, pytest-asyncio |

## Project Structure

```text
manager-bot/
|-- app/
|   |-- api/          # FastAPI app, routes, dependencies
|   |-- core/         # settings and logging
|   |-- db/           # async database session/base
|   |-- models/       # SQLAlchemy models
|   |-- schemas/      # Pydantic schemas
|   |-- services/     # business logic, imports, reports, AI helpers
|   |-- tasks/        # scheduled reminders
|   |-- telegram/     # bot handlers and keyboards
|   `-- utils/        # parsing, dates, categories, web session helpers
|-- migrations/       # Alembic migrations
|-- tests/            # parser/date tests
|-- webapp/           # Telegram WebApp frontend
|-- docs/images/      # README presentation images
|-- docker-compose.yml
|-- Dockerfile
|-- pyproject.toml
`-- README.md
```

## Quick Start

Create local environment settings:

```bash
cp .env.example .env
```

Fill the values you need:

```env
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_WEBHOOK_SECRET=your-webhook-secret
ADMIN_API_KEY=your-admin-api-key
OPENAI_API_KEY=your-openai-api-key
```

Run with Docker:

```bash
docker compose up --build
```

Useful local URLs:

```text
API:         http://localhost:8000
Healthcheck: http://localhost:8000/health/ping
```

## Local Development

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .[dev]
alembic upgrade head
uvicorn app.api.main:app --reload
```

Run tests:

```bash
pytest
```

## API Overview

| Endpoint | Description |
| --- | --- |
| `POST /telegram/webhook/{secret}` | Receives Telegram updates and forwards them to bot handlers. |
| `GET /health/ping` | Lightweight healthcheck endpoint. |
| `GET /api/v1/analytics/summary/{telegram_id}` | Monthly income, expense, balance, and category summary. |
| `GET /api/v1/analytics/kpi/{telegram_id}` | KPI dashboard data, protected by `X-API-Key`. |
| `GET /api/v1/analytics/export/{telegram_id}?days=30` | CSV export for a selected period. |
| `GET /api/v1/budgets/{telegram_id}` | User budget limits and progress. |
| `POST /api/v1/budgets/{telegram_id}` | Creates a budget limit for a category. |

## Telegram Webhook With Ngrok

For local Telegram webhook testing, fill `NGROK_AUTHTOKEN` in `.env` and keep `WEBHOOK_BASE_URL` empty. The Docker setup starts ngrok, reads the public tunnel URL from `http://localhost:4040/api/tunnels`, and registers:

```text
https://<ngrok-domain>/telegram/webhook/<secret>
```

Start the relevant services:

```bash
docker compose up --build api db redis ngrok
```

## Public Demo Boundaries

Included:

- Source code for the demo bot, API, services, migrations, tests, and WebApp.
- Placeholder `.env.example` values for reproducible setup.
- README visuals generated from local demo screenshots.

Not included:

- Real bot tokens, API keys, ngrok tokens, databases, logs, exports, caches, or virtual environments.
- Production customer data or private deployment credentials.
- Client-specific operational workflows that would not belong in a public portfolio repo.
