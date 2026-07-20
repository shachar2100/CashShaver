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

```bash
export ANTHROPIC_BASE_URL=http://localhost:4000
```

That's it — every Claude Code request now flows through the proxy and lands
as a document in MongoDB. (If you set `ANTHROPIC_REAL_API_KEY` on the proxy,
the client-side `ANTHROPIC_API_KEY` can be any placeholder value.)

### Tag requests with your email

So the dashboard / MongoDB can show who made each request, send a custom
header from Claude Code via `ANTHROPIC_CUSTOM_HEADERS`.

Single header:

```bash
export ANTHROPIC_CUSTOM_HEADERS="X-User-Email: alice@example.com"
```

Multiple headers (newline-separated; use `\n` in shell or settings JSON):

```bash
export ANTHROPIC_CUSTOM_HEADERS=$'X-User-Email: alice@example.com\nX-Team: research'
```

Or in Claude Code settings (`~/.claude/settings.json`):

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:4000",
    "ANTHROPIC_CUSTOM_HEADERS": "X-User-Email: alice@example.com"
  }
}
```

| Header          | Stored as     | Notes                                      |
|-----------------|---------------|--------------------------------------------|
| `X-User-Email`  | `user_email`  | Used for attribution in MongoDB / dashboard |

The proxy reads `X-User-Email` and **does not forward it** to Anthropic.
Without the header, `user_email` is logged as `null`.

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

## Sharing with a second person

Deploy the proxy on Fly.io or Railway pointed at a shared MongoDB (e.g. an
Atlas free tier), and point both machines' `ANTHROPIC_BASE_URL` at it. Have
each person set their own `X-User-Email` via `ANTHROPIC_CUSTOM_HEADERS` so
spend breaks down per person in MongoDB.
