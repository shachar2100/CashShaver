"""MongoDB storage for LLM request logs.

Shared by proxy.py (writes), dashboard.py and mcp_server.py (reads).
Connection settings come from .env (see .env.example).
"""

import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB = os.environ.get("MONGODB_DB", "llm_cost_proxy")
MONGODB_COLLECTION = os.environ.get("MONGODB_COLLECTION", "requests")

_client: MongoClient | None = None


def _collection():
    """Lazily created shared client; pymongo pools connections internally."""
    global _client
    if _client is None:
        _client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=10_000)
    return _client[MONGODB_DB][MONGODB_COLLECTION]


def init_db() -> None:
    coll = _collection()
    coll.create_index([("ts", DESCENDING)])
    coll.create_index([("model", ASCENDING)])
    coll.create_index([("user_email", ASCENDING)])


def insert_request(row: dict) -> None:
    # Copy so insert_one's _id injection never leaks back into caller state.
    _collection().insert_one(dict(row))


def _cutoff(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def spend_summary(days: int) -> dict:
    """Totals over the last N days: spend, tokens, request count."""
    rows = list(_collection().aggregate([
        {"$match": {"ts": {"$gte": _cutoff(days)}}},
        {"$group": {
            "_id": None,
            "requests": {"$sum": 1},
            "total_usd": {"$sum": "$cost_usd"},
            "input_tokens": {"$sum": "$input_tokens"},
            "output_tokens": {"$sum": "$output_tokens"},
            "cache_read_tokens": {"$sum": "$cache_read_tokens"},
            "cache_write_tokens": {"$sum": "$cache_write_tokens"},
        }},
        {"$project": {"_id": 0}},
    ]))
    if not rows:
        return {}
    rows[0]["total_usd"] = round(rows[0]["total_usd"], 4)
    return rows[0]


def spend_by_model(days: int) -> list[dict]:
    rows = list(_collection().aggregate([
        {"$match": {"ts": {"$gte": _cutoff(days)}}},
        {"$group": {
            "_id": "$model",
            "requests": {"$sum": 1},
            "total_usd": {"$sum": "$cost_usd"},
            "input_tokens": {"$sum": "$input_tokens"},
            "output_tokens": {"$sum": "$output_tokens"},
            "cache_read_tokens": {"$sum": "$cache_read_tokens"},
        }},
        {"$sort": {"total_usd": DESCENDING}},
        {"$project": {"_id": 0, "model": "$_id", "requests": 1, "total_usd": 1,
                      "input_tokens": 1, "output_tokens": 1, "cache_read_tokens": 1}},
    ]))
    for r in rows:
        r["total_usd"] = round(r["total_usd"], 4)
    return rows


def spend_by_day(days: int) -> list[dict]:
    rows = list(_collection().aggregate([
        {"$match": {"ts": {"$gte": _cutoff(days)}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$ts"}},
            "requests": {"$sum": 1},
            "total_usd": {"$sum": "$cost_usd"},
        }},
        {"$sort": {"_id": ASCENDING}},
        {"$project": {"_id": 0, "day": "$_id", "requests": 1, "total_usd": 1}},
    ]))
    for r in rows:
        r["total_usd"] = round(r["total_usd"], 4)
    return rows


def top_requests(days: int, limit: int) -> list[dict]:
    """The costliest individual requests, newest window first by cost."""
    docs = _collection().find(
        {"ts": {"$gte": _cutoff(days)}},
        projection={"_id": 0, "user_agent": 0, "system_hash": 0, "error": 0,
                    "streaming": 0, "status": 0,
                    "user_message": 0, "assistant_message": 0},
        sort=[("cost_usd", DESCENDING)],
        limit=limit,
    )
    out = []
    for d in docs:
        d["ts"] = d["ts"].isoformat(timespec="seconds") if d.get("ts") else None
        d["cost_usd"] = round(d.get("cost_usd") or 0.0, 4)
        out.append(d)
    return out


def cache_read_by_model(days: int) -> list[dict]:
    """Cache-read token totals per model; used to estimate caching savings."""
    return list(_collection().aggregate([
        {"$match": {"ts": {"$gte": _cutoff(days)}, "cache_read_tokens": {"$gt": 0}}},
        {"$group": {"_id": "$model", "cr": {"$sum": "$cache_read_tokens"}}},
        {"$project": {"_id": 0, "model": "$_id", "cr": 1}},
    ]))


def recent_requests(days: int) -> list[dict]:
    """Every request in the window, oldest first — feeds the dashboard DataFrame."""
    return list(_collection().find(
        {"ts": {"$gte": _cutoff(days)}},
        projection={"_id": 0},
        sort=[("ts", ASCENDING)],
    ))


if __name__ == "__main__":
    init_db()
    print(f"Connected to {MONGODB_URI}, db={MONGODB_DB}, collection={MONGODB_COLLECTION}")
