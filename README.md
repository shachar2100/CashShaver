# llm-cost-proxy

Transparent Anthropic API proxy that logs every request's tokens and cost to
SQLite, with a Streamlit dashboard and an MCP server so you can ask Claude
about your own spend.

```
Claude Code ──▶ proxy (:4000) ──▶ api.anthropic.com
                   │
                   ▼
                usage.db ◀── dashboard.py / mcp_server.py
```

## Setup

```bash
pip install fastapi uvicorn httpx pyyaml streamlit pandas "mcp[cli]"
```

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

```bash
export ANTHROPIC_BASE_URL=http://localhost:4000
```

That's it — every Claude Code request now flows through the proxy and lands
as a row in `usage.db`. (If you set `ANTHROPIC_REAL_API_KEY` on the proxy,
the client-side `ANTHROPIC_API_KEY` can be any placeholder value.)

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
- **DB location**: defaults to `usage.db` next to the code; override with
  `LLM_PROXY_DB=/path/to/db`.

## Sharing with a second person

Deploy the proxy + a volume for the SQLite file on Fly.io or Railway, point
both machines' `ANTHROPIC_BASE_URL` at it. Add a `user` column keyed off a
per-person header if you want per-person breakdowns (small change in
`_base_row`).
