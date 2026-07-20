"""Fake api.anthropic.com for local testing. Serves a realistic SSE stream."""

import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()


@app.post("/v1/messages")
async def messages(request: Request):
    body = await request.json()
    if body.get("stream"):
        async def gen():
            events = [
                ("message_start", {
                    "type": "message_start",
                    "message": {
                        "id": "msg_test", "model": "claude-sonnet-4-6-20250929",
                        "usage": {"input_tokens": 1000,
                                  "cache_creation_input_tokens": 2000,
                                  "cache_read_input_tokens": 50000,
                                  "output_tokens": 1},
                    },
                }),
                ("content_block_start", {"type": "content_block_start", "index": 0,
                                         "content_block": {"type": "text", "text": ""}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                         "delta": {"type": "text_delta", "text": "Hello"}}),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                ("message_delta", {"type": "message_delta",
                                   "delta": {"stop_reason": "end_turn"},
                                   "usage": {"output_tokens": 500}}),
                ("message_stop", {"type": "message_stop"}),
            ]
            for name, payload in events:
                yield f"event: {name}\ndata: {json.dumps(payload)}\n\n".encode()
        return StreamingResponse(gen(), media_type="text/event-stream")
    return JSONResponse({
        "id": "msg_test", "type": "message", "model": "claude-haiku-4-5-20251001",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "Hello"}],
        "usage": {"input_tokens": 300, "output_tokens": 40,
                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
    })
