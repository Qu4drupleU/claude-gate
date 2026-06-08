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
# In-memory store
# --------------------------------------------------------------------------- #
pending: dict[str, dict] = {}
decisions: dict[str, str] = {}
sse_queues: list[asyncio.Queue] = []

# --------------------------------------------------------------------------- #
# Settings.json management
# --------------------------------------------------------------------------- #

SETTINGS_PATH = os.environ.get(
    "CLAUDE_SETTINGS_PATH",
    os.path.expanduser("~/.claude/settings.json"),
)

# Tools to add to "allow" when remote mode is active
REMOTE_ALLOW = ["Bash(*)"]


def read_settings() -> dict:
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def write_settings(data: dict):
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def is_remote_mode() -> bool:
    settings = read_settings()
    allowed = settings.get("permissions", {}).get("allow", [])
    return any(r in allowed for r in REMOTE_ALLOW)


def set_remote_mode(enabled: bool):
    settings = read_settings()
    perms = settings.setdefault("permissions", {})
    allowed: list = perms.get("allow", [])

    if enabled:
        for rule in REMOTE_ALLOW:
            if rule not in allowed:
                allowed.append(rule)
    else:
        allowed = [r for r in allowed if r not in REMOTE_ALLOW]

    if allowed:
        perms["allow"] = allowed
    else:
        perms.pop("allow", None)

    if not perms:
        settings.pop("permissions", None)

    write_settings(settings)


# --------------------------------------------------------------------------- #
# Auto-restore: switch back to native mode when all SSE clients disconnect
# --------------------------------------------------------------------------- #

_restore_task: asyncio.Task | None = None

async def _delayed_restore():
    """Wait a few seconds, then restore native mode if still no clients."""
    await asyncio.sleep(5)
    if not sse_queues:
        set_remote_mode(False)
        print("[claude-gate] All clients disconnected — restored native prompt mode.")


def schedule_restore_if_empty():
    global _restore_task
    if _restore_task and not _restore_task.done():
        _restore_task.cancel()
    if not sse_queues:
        _restore_task = asyncio.create_task(_delayed_restore())


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Claude Gate", lifespan=lifespan)

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

class ModeBody(BaseModel):
    remote: bool  # True = remote mode, False = native prompt


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

async def broadcast(event: dict):
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

@app.get("/mode")
async def get_mode():
    return {"remote": is_remote_mode()}


@app.post("/mode")
async def set_mode(body: ModeBody):
    set_remote_mode(body.remote)
    await broadcast({"event": "mode_change", "remote": body.remote})
    return {"remote": body.remote}


@app.post("/request")
async def create_request(body: ToolRequest):
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
    return list(pending.values())


@app.post("/decision/{request_id}")
async def make_decision(request_id: str, body: DecisionBody):
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
    deadline = time.time() + timeout
    while time.time() < deadline:
        if request_id in decisions:
            decision = decisions.pop(request_id)
            pending.pop(request_id, None)
            return {"decision": decision}
        await asyncio.sleep(0.5)

    pending.pop(request_id, None)
    return {"decision": "deny", "reason": "timeout"}


@app.get("/events")
async def sse_stream(request: Request):
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    sse_queues.append(queue)

    # Switching to remote mode as soon as a client connects
    if not is_remote_mode():
        set_remote_mode(True)
        print("[claude-gate] Client connected — enabled remote mode.")

    async def generator() -> AsyncGenerator[str, None]:
        try:
            # Send initial state
            yield f"data: {json.dumps({'event': 'mode_change', 'remote': is_remote_mode()})}\n\n"
            for record in pending.values():
                yield f"data: {json.dumps({'event': 'new_request', 'data': record})}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            if queue in sse_queues:
                sse_queues.remove(queue)
            schedule_restore_if_empty()

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "pending_count": len(pending), "remote_mode": is_remote_mode()}
