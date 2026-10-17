"""HTTP + SSE server for the frontend -- the orchestrator as a long-running service

Starts the agent hub once and keeps it up; each request runs one question
through the orchestration graph and streams its events as Server-Sent Events.

Usage:
    python -m distributed.server                      # http://127.0.0.1:8000, hub on settings.hub_host:hub_port
    python -m distributed.server --host 0.0.0.0 --port 8000 --hub-host 0.0.0.0

Endpoints:
    GET  /api/health                    {"ok": true}
    GET  /api/departments               online departments: {name: {"device", "description"}}
    POST /api/runs        {"query"}     SSE stream of one run (fetch + ReadableStream)
    GET  /api/runs/stream?query=...     same stream, for EventSource

SSE frames: "event: <type>" + "data: <json>"; types in core/agents/streaming.py
plus run_started / done / error. The stream ends after done or error.

Key constraints:
- one run at a time (a second request gets 409) so department terminals stay readable
- a client that disconnects cancels its run
"""

import argparse
import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from core.agents.graph import build_graph, initial_state
from core.agents.streaming import SSEBridge
from distributed.hub import AgentHub
from utils.logging import setup_logging
from utils.settings import settings

TERMINAL = ("done", "error")
_args = argparse.Namespace(hub_host=settings.hub_host, hub_port=settings.hub_port)
_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.log_level)
    hub = AgentHub(_args.hub_host, _args.hub_port, settings.task_timeout_seconds)
    await hub.start()
    _state.update(hub=hub, graph=build_graph(), lock=asyncio.Lock())
    try:
        yield
    finally:
        await hub.stop()


app = FastAPI(title="Retail Rescue orchestrator", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class RunRequest(BaseModel):
    query: str


@app.get("/api/health")
async def health():
    return {"ok": True, "model": settings.llm_model}


@app.get("/api/departments")
async def departments():
    return _state["hub"].department_cards()


async def _run(query: str, queue: asyncio.Queue, run_id: str) -> None:
    """Run the graph with the SSE bridge; always ends the stream with done or error."""
    t_start = time.time()
    try:
        final = await _state["graph"].ainvoke(
            initial_state(query),
            config={"configurable": {"hub": _state["hub"], "run_id": run_id},
                    "callbacks": [SSEBridge(queue, run_id)], "recursion_limit": 100},
        )
        await queue.put({"type": "done", "run_id": run_id, "elapsed_seconds": round(time.time() - t_start, 1),
                         "report": final.get("report", "")})
    except Exception as exc:
        await queue.put({"type": "error", "run_id": run_id, "message": f"{exc.__class__.__name__}: {exc}"})


async def _stream(query: str):
    """SSE frames of one run."""
    lock: asyncio.Lock = _state["lock"]
    if lock.locked():
        raise HTTPException(status_code=409, detail="another run is in progress")
    await lock.acquire()
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_run(query, queue, run_id))

    async def frames():
        try:
            yield {"event": "run_started", "data": json.dumps(
                {"type": "run_started", "run_id": run_id, "query": query,
                 "departments": _state["hub"].department_cards()}, ensure_ascii=False)}
            while True:
                event = await queue.get()
                yield {"event": event["type"], "data": json.dumps(event, ensure_ascii=False, default=str)}
                if event["type"] in TERMINAL:
                    break
        finally:
            if not task.done():
                task.cancel()
            lock.release()

    return EventSourceResponse(frames())


@app.post("/api/runs")
async def create_run(body: RunRequest):
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="query is empty")
    return await _stream(body.query.strip())


@app.get("/api/runs/stream")
async def stream_run(query: str):
    if not query.strip():
        raise HTTPException(status_code=400, detail="query is empty")
    return await _stream(query.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the orchestrator as an HTTP + SSE service.")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host for the frontend")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port for the frontend")
    parser.add_argument("--hub-host", default=settings.hub_host, help="hub host; 0.0.0.0 for agents on other machines")
    parser.add_argument("--hub-port", type=int, default=settings.hub_port)
    args = parser.parse_args()
    _args.hub_host, _args.hub_port = args.hub_host, args.hub_port
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
