"""MCP server: ask Claude about your own token spend.

Run standalone:      python mcp_server.py
Add to Claude Code:  claude mcp add llm-costs -- python /path/to/mcp_server.py

Requires:  pip install "mcp[cli]"  (FastMCP ships inside the mcp package)
"""

from mcp.server.fastmcp import FastMCP

from db import init_db, query

init_db()
mcp = FastMCP("llm-costs")


@mcp.tool()
def get_spend(days: int = 7) -> dict:
    """Total spend, token counts, and request count over the last N days."""
    rows = query(
        """
        SELECT COUNT(*) AS requests,
               ROUND(SUM(cost_usd), 4) AS total_usd,
               SUM(input_tokens) AS input_tokens,
               SUM(output_tokens) AS output_tokens,
               SUM(cache_read_tokens) AS cache_read_tokens,
               SUM(cache_write_tokens) AS cache_write_tokens
        FROM requests
        WHERE ts >= datetime('now', ?)
        """,
        (f"-{days} days",),
    )
    return rows[0] if rows else {}


@mcp.tool()
def spend_by_model(days: int = 7) -> list[dict]:
    """Spend and token totals broken down by model over the last N days."""
    return query(
        """
        SELECT model,
               COUNT(*) AS requests,
               ROUND(SUM(cost_usd), 4) AS total_usd,
               SUM(input_tokens) AS input_tokens,
               SUM(output_tokens) AS output_tokens,
               SUM(cache_read_tokens) AS cache_read_tokens
        FROM requests
        WHERE ts >= datetime('now', ?)
        GROUP BY model
        ORDER BY SUM(cost_usd) DESC
        """,
        (f"-{days} days",),
    )


@mcp.tool()
def spend_by_day(days: int = 14) -> list[dict]:
    """Daily spend totals for the last N days — useful for trend questions."""
    return query(
        """
        SELECT substr(ts, 1, 10) AS day,
               COUNT(*) AS requests,
               ROUND(SUM(cost_usd), 4) AS total_usd
        FROM requests
        WHERE ts >= datetime('now', ?)
        GROUP BY day
        ORDER BY day
        """,
        (f"-{days} days",),
    )


@mcp.tool()
def most_expensive_requests(limit: int = 10, days: int = 7) -> list[dict]:
    """The costliest individual requests in the last N days."""
    return query(
        """
        SELECT ts, model, input_tokens, output_tokens, cache_read_tokens,
               cache_write_tokens, ROUND(cost_usd, 4) AS cost_usd,
               latency_ms, stop_reason, endpoint
        FROM requests
        WHERE ts >= datetime('now', ?)
        ORDER BY cost_usd DESC
        LIMIT ?
        """,
        (f"-{days} days", limit),
    )


@mcp.tool()
def cache_savings(days: int = 7) -> dict:
    """Estimate dollars saved by prompt caching: what cache-read tokens
    would have cost at full input price minus what they actually cost."""
    rows = query(
        """
        SELECT model, SUM(cache_read_tokens) AS cr
        FROM requests
        WHERE ts >= datetime('now', ?) AND cache_read_tokens > 0
        GROUP BY model
        """,
        (f"-{days} days",),
    )
    import yaml, os
    with open(os.path.join(os.path.dirname(__file__), "pricing.yaml")) as f:
        pricing = yaml.safe_load(f)["models"]
    saved = 0.0
    for r in rows:
        model = r["model"] or ""
        match = max((p for p in pricing if model.startswith(p)), key=len, default=None)
        if match:
            rates = pricing[match]
            saved += r["cr"] * (rates["input"] - rates["cache_read"]) / 1_000_000
    return {"days": days, "estimated_usd_saved_by_prompt_caching": round(saved, 4)}


if __name__ == "__main__":
    mcp.run()
