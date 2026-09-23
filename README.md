# Data Insight Agent

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Self-hosted AI business analyst.** Point it at a CSV / Excel file, ask a question in plain language, and get a business diagnostic report where **every conclusion can be checked** — each finding carries the SQL it ran, the data source, and the run time. No black-box summaries.

[简体中文 →](README.zh-CN.md)

## Why it's different

Most "chat with your data" tools give you answers you take on faith, on someone else's servers, with their model. This one:

- **Writes verifiable reports, not chat replies.** Every conclusion links to its SQL, data source and run time. Reports are built for review and sharing, with PDF export.
- **Runs on your machine.** Deploy with Docker. The product vendor never hosts or sees your data.
- **Bring your own model (BYOM).** Any OpenAI-compatible API works — OpenAI, DeepSeek, Qwen, OpenRouter, local Ollama. You control the model and the data path.
- **Industry context packs.** Analysis is grounded in an industry semantic layer — metric definitions, dimensions, analysis templates, validation rules — instead of generic prompting. Retail operations is the first built-in pack.

## What it does

1. Upload a CSV or `.xlsx`, or load the built-in retail sample with one click.
2. Describe what you want to know, e.g. *"Compare this week vs last week and flag underperforming stores."*
3. It parses your goal into a structured task for you to confirm, then runs a bounded analysis loop: query, drill down, chart.
4. You get a report with key metrics, findings, charts and suggested next steps — every conclusion has a "view evidence" toggle.
5. Reports and datasets are persisted: browse history read-only, re-open past reports, export to PDF.
6. Save a report as a reusable analysis task. Next period, upload a file with the same structure and rerun it: the new report joins the task's report chain and opens with a "vs. previous report" section whose KPI changes are computed by the system, not the model, with a link back to the previous report. A file with a different structure is stopped before the run, with the missing / extra fields listed.
7. Edit the business rules the analysis runs on — metric definitions, field aliases, anomaly thresholds — in the web UI, with server-side validation and one-click reset. Every report records the rule version it was generated with.
8. Mark any report useful / not useful with a one-line note; feedback stays in your local database.

## Quick start

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
docker compose up -d
```

- App: <http://localhost:8000> (frontend and API in one container)
- Health check: <http://localhost:8000/health>

First run pulls a prebuilt multi-arch image from ghcr. **It works without a model**: use the sample-report entry on the home screen to run the full flow on built-in retail data (demo mode, fully offline).

## Configure your model

To analyze your own data with natural language, configure any OpenAI-compatible endpoint. Two ways:

- **In the UI (recommended)**: sidebar → model settings — pick a provider preset or a custom base URL, test the connection, save. The key is stored locally with file permissions `600`, masked in responses, and never written to logs or reports.
- **Via `.env`**:

```bash
cp .env.example .env
#   LLM_API_KEY   your key
#   LLM_PROVIDER  preset name (e.g. deepseek / openai / openrouter), or leave empty and set:
#   LLM_BASE_URL  custom OpenAI-compatible endpoint
#   LLM_MODEL     model name
docker compose up -d   # restart to apply
```

## Data & privacy

- The vendor hosts nothing. The app runs on your machine; analysis data lives in a local SQLite file and temporary upload files.
- When a remote model is configured, the data schema, aggregated query results and prompts are sent to **the model provider you chose** — raw row-level records are not sent.
- Demo mode (no model configured) runs fully locally and sends nothing anywhere.

## Roadmap

- Scheduled recurring reports with email / webhook / IM-card push (next up)
- MySQL / PostgreSQL read-only connections
- One-command local run via `uvx`; English UI (the UI is currently Chinese-first)
- Second industry pack: SaaS operations

## Requirements

- Docker Desktop (recommended path, the only hard requirement).
- Local development (optional): Python 3.11+, Node 22.13+, `uv`, `pnpm` (the version is pinned by `packageManager` in `frontend/package.json`).

## Local development (optional)

```bash
make dev            # start backend + frontend
make backend-dev    # backend only
make frontend-dev   # frontend only
make check          # backend lint+tests, frontend typecheck+lint+tests+build
make smoke          # build the Docker image from source, start it, check /health and /
make eval           # report-quality eval: golden questions against your configured model, in an isolated temp database
```

`http://localhost:5173` is the Vite dev server and proxies `/api` to `http://127.0.0.1:8000`, so the backend must be running for reports, samples and uploads.

## FAQ

- **Port 8000 is blank / unreachable**: make sure `docker compose up -d` succeeded and the container is running (the first run pulls the image from ghcr — give it a moment).
- **Report generation says the model is not configured**: without a model only the built-in retail sample works (demo mode). Configure a model to analyze your own data.
- **Upload fails**: plain two-dimensional tables with a header row are supported (CSV and `.xlsx`). Complex headers, merged cells and pivot sheets are not supported yet.
- **The UI is in Chinese**: an English UI is on the roadmap; report structure (metrics, charts, SQL evidence) is readable regardless.

## Architecture

Three layers: a deterministic workflow shell (scheduling, data connections, report assembly) + a bounded agentic analysis core (fixed tool set, hard iteration cap, every SQL statement passes an execution-control layer) + industry context packs (the semantic layer). Contract: [docs/architecture.md](docs/architecture.md).

## License

[MIT](LICENSE)
