"""SQLite storage for LLM request logs.

Shared by proxy.py (writes), dashboard.py and mcp_server.py (reads).
WAL mode lets readers work while the proxy writes.
"""

import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("LLM_PROXY_DB", os.path.join(os.path.dirname(__file__), "usage.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,                  -- ISO-8601 UTC timestamp of request start
  model TEXT,
  input_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  cache_read_tokens INTEGER DEFAULT 0,
  cache_write_tokens INTEGER DEFAULT 0,
  cost_usd REAL DEFAULT 0.0,
  latency_ms INTEGER,
  stop_reason TEXT,
  streaming INTEGER DEFAULT 0,
  status INTEGER,
  endpoint TEXT,
  user_agent TEXT,
  system_hash TEXT,                  -- hash of system prompt; groups sessions
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_requests_ts ON requests (ts);
CREATE INDEX IF NOT EXISTS idx_requests_model ON requests (model);
"""


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def insert_request(row: dict) -> None:
    cols = [
        "ts", "model", "input_tokens", "output_tokens", "cache_read_tokens",
        "cache_write_tokens", "cost_usd", "latency_ms", "stop_reason",
        "streaming", "status", "endpoint", "user_agent", "system_hash", "error",
    ]
    values = [row.get(c) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    with _connect() as conn:
        conn.execute(
            f"INSERT INTO requests ({', '.join(cols)}) VALUES ({placeholders})",
            values,
        )


def query(sql: str, params: tuple = ()) -> list[dict]:
    """Read-only helper used by the MCP server and dashboard."""
    with _connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


if __name__ == "__main__":
    init_db()
    print(f"Initialized {DB_PATH}")
