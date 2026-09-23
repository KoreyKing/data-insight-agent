# Data Insight Agent

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Self-hosted AI business analyst.** Point it at a CSV / Excel file, say what you want to know in plain language, and get a business diagnostic report where **every conclusion can be checked**: each finding carries the SQL it ran, the data source and the run time.

[简体中文 →](README.zh-CN.md)

![Report view: KPI cards, a finding with its chart, and the SQL evidence behind it](.github/assets/product-report.png)

<sub>A report on the built-in retail sample, generated with an OpenAI-compatible model. The UI is currently Chinese-first.</sub>

## Why it's different

- **Verifiable reports, not chat replies.** Every conclusion links to its SQL, data source and run time, and KPI changes are computed by the system rather than written by the model. Reports export to PDF.
- **Runs on your machine.** One Docker container. Nobody but you hosts or sees your data.
- **Bring your own model.** Any OpenAI-compatible API: OpenAI, DeepSeek, Qwen (DashScope), Kimi, Zhipu GLM, Gemini, OpenRouter, or a local Ollama / vLLM server.
- **Business rules you can edit.** Analysis is grounded in an industry context pack — metric definitions, field aliases, anomaly thresholds — that you adjust in the UI. Retail operations is the first built-in pack.

## What you can do

- **Analyze a file.** Upload a CSV / `.xlsx` (or load the built-in retail sample), describe your goal, confirm the structured task, and get a report with key metrics, findings, charts and suggested next steps.
- **Rerun next period.** Save a report as a task, then upload next period's file with the same structure and rerun it. The new report opens with a "vs. previous report" section. A file with a different structure is stopped before the run, with the missing / extra fields listed.
- **Edit business rules.** Change metric definitions, field aliases and anomaly thresholds, with server-side validation and one-click reset. Every report records the rule version it was generated with.
- **Keep a history.** Past reports and datasets stay browsable. Mark any report useful / not useful with a one-line note; feedback stays in your local database.

## Quick start

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine with Compose v2).

```bash
git clone https://github.com/KoreyKing/data-insight-agent.git
cd data-insight-agent
docker compose up -d
```

Open <http://localhost:8000>. The first run pulls a prebuilt image (amd64 / arm64) from ghcr.

**No model is needed to try it.** Click 「使用零售样例」 (use the retail sample) and run the full flow in demo mode: a deterministic report on built-in data, with no model calls.

## Configure your model

To analyze your own data, configure an OpenAI-compatible endpoint:

- **In the UI (recommended):** sidebar → model settings. Pick a preset or enter a base URL, test the connection, save. The key is stored in `data/llm_config.json` (file permissions `600`), masked in responses and never written to logs or reports. UI settings take precedence over `.env`.
- **Via `.env`:**

```bash
cp .env.example .env
#   LLM_PROVIDER  preset (openai / deepseek / dashscope / kimi / zhipu /
#                 gemini / openrouter / ollama / vllm) or custom
#   LLM_BASE_URL  endpoint (required for custom, optional with a preset)
#   LLM_API_KEY   your key
#   LLM_MODEL     model name
docker compose up -d --force-recreate   # apply the new settings
```

Pick a model that follows JSON instructions reliably; very small models tend to break the analysis loop.

## Use your own data

- **Format:** plain tables with a single header row — CSV (UTF-8) or `.xlsx` (choose the sheet in the UI). Merged cells, multi-row headers and pivot tables are not supported.
- **Columns:** one row per order line. An **order date** and a **net sales amount** are required. Store, product category and channel enable drill-down; order ID, order status, refund amount and unit cost enable accurate order counts, refund rate and gross margin.
- **Column names** are matched through aliases, e.g. `订单日期` / `date`, `门店` / `store`, `销售额` / `net_sales`. If a column is not recognized, add your header as an alias in 「业务口径设置」 (business rules).
- **Order status**, if present, is normalized automatically: common spellings such as `已完成` / `交易成功` / `paid`, `部分退款` / `partially refunded` and `已退款` / `returned` map to completed, partial refund and refunded. Rows whose status it can't recognize (e.g. `已取消`) are left out of every core metric (sales, orders, average order value and refund rate), and when the report finishes, the analysis conversation shows how many rows were affected. Without an order-status column every row counts as completed.

## Data & privacy

- Everything stays on your machine: reports, datasets and settings live in `./data` (a SQLite file plus uploaded files).
- With a remote model configured, the data schema, aggregated query results and prompt text are sent to **the model provider you chose**. Raw row-level records are not sent.
- Demo mode makes no model calls, and the web UI loads no third-party resources (fonts ship with the app).

## Security

- There is **no login or user management**. Anyone who can reach port 8000 can read your reports and change the model settings.
- `docker-compose.yml` binds port 8000 to `127.0.0.1`, so only this machine can open the app. To reach it from other devices, change the mapping to `"8000:8000"` and use it only on a trusted network. Do not expose the app to the internet without an authenticating reverse proxy in front of it.

## Upgrade & backup

```bash
docker compose pull
docker compose up -d
```

The database structure upgrades automatically on startup (new tables and columns only; existing data is kept). Business rules you never edited follow the new factory version; edited rules are kept as they are (reset them in 「业务口径设置」 to adopt the new defaults). Back up the `./data` directory before upgrading.

## Current limitations

- One data model: a single retail sales table, through the built-in retail pack.
- Reports run on demand; scheduled runs and push delivery are not available yet.
- The UI is Chinese-first.
- The written analysis can over-generalize. The numbers are reproducible, so check them against the attached SQL before acting on a conclusion.
- Single user, no access control (see [Security](#security)).

## Roadmap

- Scheduled recurring reports with email / webhook / IM-card push
- MySQL / PostgreSQL read-only connections
- One-command local run via `uvx`; English UI
- A second industry pack: SaaS operations

## FAQ

- **Port 8000 is blank or unreachable:** check that `docker compose up -d` succeeded and the container is running; the first run needs time to pull the image. From another device, see [Security](#security): the port only listens on this machine by default.
- **"Model not configured":** without a model only the built-in sample works (demo mode). Configure a model to analyze your own files.
- **Ollama / vLLM on the same machine doesn't connect:** inside Docker, `localhost` is the container itself. Use a custom base URL such as `http://host.docker.internal:11434/v1` (Docker Desktop; on Linux, add `extra_hosts: ["host.docker.internal:host-gateway"]` to the service).
- **Upload fails or fields are missing:** see [Use your own data](#use-your-own-data).

## Development

Requires Python 3.11+, Node 22.13+, `uv` and `pnpm` (the version is pinned by `packageManager` in `frontend/package.json`).

```bash
make dev     # backend + frontend (Vite on http://localhost:5173, /api proxied to :8000)
make check   # backend lint + tests, frontend typecheck + lint + tests + build
make smoke   # build the Docker image from source, start it, check /health and /
make eval    # report-quality eval against your configured model, in an isolated temp database
```

- **Architecture and API contracts:** [docs/architecture.md](docs/architecture.md). Three layers: a deterministic workflow shell (data connections and report assembly; scheduling and push are planned), a bounded agentic analysis core (fixed tool set, hard iteration cap, every SQL statement validated) and industry context packs.
- **Engineering conventions**, also read by AI coding assistants: [CLAUDE.md](CLAUDE.md) / [AGENTS.md](AGENTS.md).
- **Feedback:** bug reports and ideas go to GitHub Issues. This repository is published from the maintainer's workspace, so please open an issue to discuss a change before sending a pull request.

## License

[MIT](LICENSE)
