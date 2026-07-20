"""MCP server: ask Claude about your own token spend.

Run standalone:      python mcp_server.py
Add to Claude Code:  claude mcp add llm-costs -- python /path/to/mcp_server.py

Requires:  pip install "mcp[cli]"  (FastMCP ships inside the mcp package)
"""

import os

import yaml
from mcp.server.fastmcp import FastMCP

import db

db.init_db()
mcp = FastMCP("llm-costs")


@mcp.tool()
def get_spend(days: int = 7) -> dict:
    """Total spend, token counts, and request count over the last N days."""
    return db.spend_summary(days)


@mcp.tool()
def spend_by_model(days: int = 7) -> list[dict]:
    """Spend and token totals broken down by model over the last N days."""
    return db.spend_by_model(days)


@mcp.tool()
def spend_by_day(days: int = 14) -> list[dict]:
    """Daily spend totals for the last N days — useful for trend questions."""
    return db.spend_by_day(days)


@mcp.tool()
def most_expensive_requests(limit: int = 10, days: int = 7) -> list[dict]:
    """The costliest individual requests in the last N days."""
    return db.top_requests(days, limit)


@mcp.tool()
def cache_savings(days: int = 7) -> dict:
    """Estimate dollars saved by prompt caching: what cache-read tokens
    would have cost at full input price minus what they actually cost."""
    rows = db.cache_read_by_model(days)
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
