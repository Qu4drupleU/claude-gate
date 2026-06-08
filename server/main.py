import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# --------------------------------------------------------------------------- #
# In-memory store (swap for Redis / SQLite if you want persistence across restart)
# --------------------------------------------------------------------------- #
pending: dict[str, dict] = {}          # request_id -> request details
decisions: dict[str, str] = {}         # request_id -> "allow" | "deny"
sse_queues: list[asyncio.Queue] = []   # one per connected SSE client


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Claude Remote Approval", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #

class ToolRequest(BaseModel):
    tool_name: str
    tool_input: dict
    session_id: str | None = None
    cwd: str | None = None

class DecisionBody(BaseModel):
    decision: str  # "allow" | "deny"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

async def broadcast(event: dict):
    """Push an event to all connected SSE clients."""
    data = json.dumps(event)
    dead = []
    for q in sse_queues:
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        sse_queues.remove(q)


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@app.post("/request")
async def create_request(body: ToolRequest):
    """Hook script calls this to register a pending approval."""
    request_id = str(uuid.uuid4())
    record = {
        "id": request_id,
        "tool_name": body.tool_name,
        "tool_input": body.tool_input,
        "session_id": body.session_id,
        "cwd": body.cwd,
        "created_at": time.time(),
        "status": "pending",
    }
    pending[request_id] = record
    await broadcast({"event": "new_request", "data": record})
    return {"request_id": request_id}


@app.get("/pending")
async def list_pending():
    """Web / iOS app calls this to get all pending requests."""
    return list(pending.values())


@app.post("/decision/{request_id}")
async def make_decision(request_id: str, body: DecisionBody):
    """Web / iOS app posts allow or deny here."""
    if request_id not in pending:
        raise HTTPException(404, "Request not found")
    if body.decision not in ("allow", "deny"):
        raise HTTPException(400, "decision must be 'allow' or 'deny'")

    decisions[request_id] = body.decision
    pending[request_id]["status"] = body.decision
    await broadcast({"event": "decision", "request_id": request_id, "decision": body.decision})
    return {"ok": True}


@app.get("/poll/{request_id}")
async def poll_decision(request_id: str, timeout: int = 300):
    """
    Hook script calls this to long-poll for a decision.
    Blocks (up to `timeout` seconds) until a decision arrives.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if request_id in decisions:
            decision = decisions.pop(request_id)
            pending.pop(request_id, None)
            return {"decision": decision}
        await asyncio.sleep(0.5)

    # Timed out — auto-deny to unblock Claude Code
    pending.pop(request_id, None)
    return {"decision": "deny", "reason": "timeout"}


@app.get("/events")
async def sse_stream(request: Request):
    """Server-Sent Events endpoint for the web dashboard."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    sse_queues.append(queue)

    async def generator() -> AsyncGenerator[str, None]:
        try:
            # Send current pending requests on connect
            for record in pending.values():
                yield f"data: {json.dumps({'event': 'new_request', 'data': record})}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"  # keep connection alive
        finally:
            if queue in sse_queues:
                sse_queues.remove(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok", "pending_count": len(pending)}
