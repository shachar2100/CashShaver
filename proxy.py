"""Transparent Anthropic API proxy that logs token usage and cost.

Point Claude Code at it:
    export ANTHROPIC_BASE_URL=http://localhost:4000
    (keep your normal ANTHROPIC_API_KEY, or set a real key server-side
     via ANTHROPIC_REAL_API_KEY so laptops never hold it)

Run:
    uvicorn proxy:app --port 4000
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone

import httpx
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse

from db import init_db, insert_request

UPSTREAM = os.environ.get("LLM_PROXY_UPSTREAM", "https://api.anthropic.com")
REAL_KEY = os.environ.get("ANTHROPIC_REAL_API_KEY")  # optional server-side key

log = logging.getLogger("llm-cost-proxy")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI()
client: httpx.AsyncClient | None = None

with open(os.path.join(os.path.dirname(__file__), "pricing.yaml")) as f:
    PRICING: dict = yaml.safe_load(f)["models"]

# Headers that must not be blindly forwarded in either direction.
# x-user-email is ours (attribution only) — strip it before calling Anthropic.
HOP_HEADERS = {
    "host", "content-length", "transfer-encoding", "connection", "keep-alive",
    "x-user-email",
}


@app.on_event("startup")
async def startup() -> None:
    global client
    init_db()
    client = httpx.AsyncClient(base_url=UPSTREAM, timeout=httpx.Timeout(600.0, connect=10.0))
    log.info("Proxying to %s, logging to MongoDB", UPSTREAM)


@app.on_event("shutdown")
async def shutdown() -> None:
    if client:
        await client.aclose()


def price(model: str | None, usage: dict) -> float:
    """Cost in USD from a usage dict, longest-prefix match on model name."""
    if not model:
        return 0.0
    best = None
    for prefix, rates in PRICING.items():
        if model.startswith(prefix) and (best is None or len(prefix) > len(best)):
            best = prefix
    if best is None:
        log.warning("No pricing entry for model %s — logging cost as 0", model)
        return 0.0
    r = PRICING[best]
    return (
        usage.get("input_tokens", 0) * r["input"]
        + usage.get("output_tokens", 0) * r["output"]
        + usage.get("cache_read_tokens", 0) * r["cache_read"]
        + usage.get("cache_write_tokens", 0) * r["cache_write"]
    ) / 1_000_000


def _system_hash(body: dict) -> str | None:
    """Stable short hash of the system prompt — groups requests by session type."""
    system = body.get("system")
    if system is None:
        return None
    raw = json.dumps(system, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _last_user_text(body: dict) -> str | None:
    """Text of the most recent human-authored message.

    User-role messages containing only tool_result blocks are skipped so
    tool output isn't mistaken for something the user typed.
    """
    for msg in reversed(body.get("messages") or []):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = [b.get("text", "") for b in content
                     if isinstance(b, dict) and b.get("type") == "text"]
            if texts:
                return "\n".join(texts)
    return None


def _response_text(content: list) -> str | None:
    """Concatenated text blocks from a messages-API response content list."""
    texts = [b.get("text", "") for b in content
             if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(texts) if texts else None


def _extract_usage_fields(usage: dict) -> dict:
    """Normalize an Anthropic usage object into our column names."""
    return {
        "input_tokens": usage.get("input_tokens", 0) or 0,
        "output_tokens": usage.get("output_tokens", 0) or 0,
        "cache_read_tokens": usage.get("cache_read_input_tokens", 0) or 0,
        "cache_write_tokens": usage.get("cache_creation_input_tokens", 0) or 0,
    }


async def _write_row(row: dict) -> None:
    """Insert off the event loop so the stream is never blocked on the DB write."""
    row["cost_usd"] = price(row.get("model"), row)
    try:
        await asyncio.to_thread(insert_request, row)
    except Exception:
        log.exception("Failed to write usage row")


def _base_row(request: Request, body: dict | None, streaming: bool) -> dict:
    return {
        "ts": datetime.now(timezone.utc),
        "model": (body or {}).get("model"),
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "latency_ms": None,
        "stop_reason": None,
        "streaming": int(streaming),
        "status": None,
        "endpoint": request.url.path,
        "user_agent": request.headers.get("user-agent"),
        # Clients set this via ANTHROPIC_CUSTOM_HEADERS="X-User-Email: you@example.com"
        "user_email": request.headers.get("x-user-email"),
        "system_hash": _system_hash(body) if body else None,
        "user_message": _last_user_text(body) if body else None,
        "assistant_message": None,
        "error": None,
    }


class SSETap:
    """Incremental SSE parser: feed raw bytes, it collects usage/stop_reason.

    Chunks can split lines anywhere, so we keep a byte buffer and only
    parse complete lines.
    """

    def __init__(self) -> None:
        self._buf = b""
        self.usage: dict = {}
        self.stop_reason: str | None = None
        self.model: str | None = None
        self._text: list[str] = []

    @property
    def text(self) -> str | None:
        return "".join(self._text) or None

    def feed(self, chunk: bytes) -> None:
        self._buf += chunk
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            line = line.strip()
            if not line.startswith(b"data:"):
                continue
            payload = line[len(b"data:"):].strip()
            if not payload or payload == b"[DONE]":
                continue
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            etype = event.get("type")
            if etype == "message_start":
                msg = event.get("message", {})
                self.model = msg.get("model") or self.model
                self.usage.update(_extract_usage_fields(msg.get("usage", {})))
            elif etype == "message_delta":
                usage = event.get("usage", {})
                if "output_tokens" in usage:
                    self.usage["output_tokens"] = usage["output_tokens"]
                # Late-arriving input/cache counts also land here on some models
                for k, col in (
                    ("input_tokens", "input_tokens"),
                    ("cache_read_input_tokens", "cache_read_tokens"),
                    ("cache_creation_input_tokens", "cache_write_tokens"),
                ):
                    if k in usage:
                        self.usage[col] = usage[k]
                delta = event.get("delta", {})
                self.stop_reason = delta.get("stop_reason") or self.stop_reason
            elif etype == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    self._text.append(delta.get("text", ""))
            elif etype == "error":
                self.stop_reason = "error"


def _outbound_headers(request: Request) -> dict:
    headers = {
        k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS
    }
    # Ask upstream for uncompressed bytes: the SSE tap parses the raw relay
    # stream, and gzip/brotli chunks would be opaque to it.
    headers["accept-encoding"] = "identity"
    if REAL_KEY:
        headers["x-api-key"] = REAL_KEY
        headers.pop("authorization", None)
    return headers


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def relay(request: Request, path: str):
    raw_body = await request.body()
    body: dict | None = None
    if raw_body:
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            body = None
    streaming = bool(body and body.get("stream"))
    row = _base_row(request, body, streaming)
    started = time.monotonic()

    upstream_req = client.build_request(
        request.method,
        f"/{path}" + (f"?{request.url.query}" if request.url.query else ""),
        headers=_outbound_headers(request),
        content=raw_body or None,
    )

    try:
        upstream = await client.send(upstream_req, stream=True)
    except httpx.HTTPError as exc:
        row.update(status=502, error=f"upstream connection error: {exc}",
                   latency_ms=int((time.monotonic() - started) * 1000))
        asyncio.create_task(_write_row(row))
        return Response(
            content=json.dumps({"type": "error",
                                "error": {"type": "api_error",
                                          "message": "proxy could not reach upstream"}}),
            status_code=502, media_type="application/json",
        )

    row["status"] = upstream.status_code
    resp_headers = {
        k: v for k, v in upstream.headers.items() if k.lower() not in HOP_HEADERS
    }
    is_sse = "text/event-stream" in upstream.headers.get("content-type", "")

    if is_sse:
        tap = SSETap()

        async def relay_stream():
            try:
                async for chunk in upstream.aiter_raw():
                    tap.feed(chunk)
                    yield chunk
            finally:
                await upstream.aclose()
                row.update(tap.usage)
                row["model"] = tap.model or row["model"]
                row["stop_reason"] = tap.stop_reason
                row["assistant_message"] = tap.text
                row["latency_ms"] = int((time.monotonic() - started) * 1000)
                asyncio.create_task(_write_row(row))

        return StreamingResponse(relay_stream(),
                                 status_code=upstream.status_code,
                                 headers=resp_headers)

    # Non-streaming: read fully, tap the JSON body, relay as-is.
    content = await upstream.aread()
    await upstream.aclose()
    row["latency_ms"] = int((time.monotonic() - started) * 1000)
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            if "usage" in data:
                row.update(_extract_usage_fields(data["usage"]))
                row["model"] = data.get("model") or row["model"]
                row["stop_reason"] = data.get("stop_reason")
            if isinstance(data.get("content"), list):
                row["assistant_message"] = _response_text(data["content"])
            if data.get("type") == "error":
                row["error"] = json.dumps(data.get("error"))
    except json.JSONDecodeError:
        pass
    # Only log endpoints that consumed tokens or failed — skip health checks etc.
    if request.method == "POST" or row["status"] >= 400:
        asyncio.create_task(_write_row(row))
    return Response(content=content,
                    status_code=upstream.status_code,
                    headers=resp_headers)
