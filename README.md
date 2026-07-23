# llm-cost-proxy

Transparent Anthropic API proxy that logs every request's tokens and cost to
MongoDB, with a Streamlit dashboard and an MCP server so you can ask Claude
about your own spend.

```
Claude Code ──▶ proxy (:4000) ──▶ api.anthropic.com
                   │
                   ▼
                MongoDB ◀── dashboard.py / mcp_server.py
```

## Setup

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set `MONGODB_URI` to your MongoDB
connection string (local instance or Atlas). `MONGODB_DB` and
`MONGODB_COLLECTION` control where rows land (defaults:
`llm_cost_proxy.requests`).

## Run the proxy

```bash
uvicorn proxy:app --port 4000
```

Optionally hold the real key server-side so laptops never see it:

```bash
export ANTHROPIC_REAL_API_KEY=sk-ant-...
uvicorn proxy:app --port 4000
```

## Point Claude Code at it

Put your username in the base URL path so every request is attributed:

```bash
# local
export ANTHROPIC_BASE_URL=http://localhost:4000/alice

# Cloud Run
export ANTHROPIC_BASE_URL=https://cashshaver-proxy-xxxxx.run.app/alice
```

Claude Code then calls `/alice/v1/messages`; the proxy stores `username: "alice"`
and forwards `/v1/messages` to Anthropic. Usernames are letters/digits plus
`.`, `_`, `-` (max 64 chars).

Or in Claude Code settings (`~/.claude/settings.json`):

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://cashshaver-proxy-xxxxx.run.app/alice"
  }
}
```

Without a username prefix (`…run.app` with no path), `username` is logged as
`null`. (If you set `ANTHROPIC_REAL_API_KEY` on the proxy, the client-side
`ANTHROPIC_API_KEY` can be any placeholder value.)

## Dashboard

```bash
streamlit run dashboard.py
```

Spend by day, by model, token composition, cache savings, priciest requests,
and errors. Auto-refreshes data every 30s.

## MCP server (ask Claude about your spend)

```bash
claude mcp add llm-costs -- python /full/path/to/mcp_server.py
```

Then in Claude Code: *"how much did I spend this week and which model ate it?"*
Tools exposed: `get_spend`, `spend_by_model`, `spend_by_day`,
`most_expensive_requests`, `cache_savings`.

## Maintenance notes

- **Pricing**: `pricing.yaml` was verified July 2026. Re-check rates at
  https://platform.claude.com/docs/en/about-claude/pricing when new models
  ship. **Sonnet 5 intro pricing ends 2026-08-31 — update the file then.**
- **1-hour cache**: cache writes are priced at the 5-minute rate (1.25x
  input). If you use `ttl: 1h` caching heavily, writes are billed at 2x and
  this table will undercount — split the rate if that's your workload.
- **Unknown models** log with cost 0 and a warning rather than a guess, so
  they're visible in the dashboard instead of silently mispriced.
- **DB location**: set `MONGODB_URI` / `MONGODB_DB` / `MONGODB_COLLECTION`
  in `.env` (defaults: `mongodb://localhost:27017`, `llm_cost_proxy`,
  `requests`).

## Deploy (Google Cloud Run)

The repo includes a `Dockerfile` + `deploy-cloudrun.sh` that run **only the
proxy** (not the dashboard or MCP server). Transparent mode: do **not** set
`ANTHROPIC_REAL_API_KEY` on Cloud Run — clients keep using their own keys.

### One-time setup

```bash
# gcloud is installed via: brew install --cask google-cloud-sdk
gcloud auth login
gcloud auth application-default login
```

Create (or pick) a GCP project with billing enabled, then in Atlas →
**Network Access** allow `0.0.0.0/0` so Cloud Run can reach MongoDB.

### Deploy

```bash
# from the repo root; script reads MONGODB_* from .env
./deploy-cloudrun.sh YOUR_GCP_PROJECT_ID us-east1
```

That enables Cloud Run / Cloud Build, builds the container from the
`Dockerfile`, and sets `MONGODB_URI` / `MONGODB_DB` / `MONGODB_COLLECTION`.

### Point Claude Code at it

```bash
export ANTHROPIC_BASE_URL=https://cashshaver-proxy-xxxxx-ue.a.run.app/alice
claude
```

## Sharing with a second person

Deploy once to Cloud Run against shared Atlas. Each person uses the same host
with their own username path, e.g. `…run.app/alice` vs `…run.app/bob`, so
spend breaks down per person in MongoDB.
