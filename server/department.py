"""Loopback dashboard + agent runtime for one department device.

Run this INSTEAD OF distributed.agent on a device, not alongside it:
    python -m server.department --department product --port 8101
The hub still receives only progress metadata and the owner-approved result.
Local model/tool output is streamed solely to this device's dashboard.
"""

import argparse
import asyncio
import json
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, StrictBool
from sse_starlette.sse import EventSourceResponse
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from core.agents.worker.graph import build_department_graph, run_department_task
from core.departments import DEVICES_DIR, load_card
from core.tools._kernel._access import department_policy
from distributed.constants import MAX_FRAME_BYTES, PING_INTERVAL_SECONDS, PING_TIMEOUT_SECONDS, RECONNECT_DELAY_SECONDS
from distributed.protocol import EVENT, REGISTER, REGISTER_ACK, RESULT, TASK, ProtocolError, decode, encode
from server.callbacks import CompletionCallbackHandler
from utils.logging import setup_logging
from utils.run_log import capture
from utils.settings import settings


class LocalCallback(CompletionCallbackHandler):
    """Reuse tool payloads, but show this department's own model output locally."""

    def __init__(self, runtime, run_id):
        super().__init__(asyncio.Queue())
        self.runtime, self.run_id = runtime, run_id

    async def put(self, delta):
        self.runtime.delta(self.run_id, delta.model_dump(exclude_none=True))

    async def on_chat_model_start(self, serialized, messages, *, run_id, metadata=None, **kwargs):
        node = (metadata or {}).get("langgraph_node", "")
        self._models[run_id] = ("announce" if node == "agent" else "", False)
        if node == "agent" and self.runtime.tasks[self.run_id]["content"]:
            await self.text("\n\n")

    async def on_tool_end(self, output, *, run_id, **kwargs):
        if isinstance(output, str) and output.startswith("Not run:"):
            await self.on_tool_error(RuntimeError(output), run_id=run_id)
        else:
            await super().on_tool_end(output, run_id=run_id, **kwargs)


def file_inventory(card, policy):
    """Names and sizes only; never follow symlinks or read file contents."""
    def walk(root, relative, locked=False, depth=0, budget=None):
        budget = budget if budget is not None else [160]
        entries = []
        try:
            children = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return entries
        for path in children:
            if budget[0] <= 0:
                break
            if path.is_symlink() or path.name.startswith("."):
                continue
            budget[0] -= 1
            try:
                folder = path.is_dir()
                item = {"name": path.name, "path": f"{relative}/{path.name}",
                        "kind": "folder" if folder else "file", "locked": locked}
                if folder and depth < 3:
                    item["children"] = walk(path, item["path"], locked, depth + 1, budget)
                elif not folder:
                    item["size"] = path.stat().st_size
                entries.append(item)
            except OSError:
                continue
        return entries

    return [{"name": name, "path": name, "kind": "folder", "locked": locked,
             "children": walk(Path(root), name, locked)}
            for name, root, locked in [("shared", card.shared_dir, False),
                                       ("private", card.private_dir, True),
                                       ("workspace", policy.workspace, False)]]


class DepartmentRuntime:
    def __init__(self, card, policy, device_id, hub_url, *, graph=None, approval_timeout=None, log_session=None):
        self.card, self.policy = card, policy
        self.device_id, self.hub_url, self.graph = device_id, hub_url, graph
        self.log_session = log_session
        self.approval_timeout = settings.approval_timeout_seconds if approval_timeout is None else approval_timeout
        self.connection, self.connection_message = "connecting", "Connecting to coordinator"
        self.tasks: dict[str, dict] = {}
        self.pending: dict[str, tuple[dict, asyncio.Future]] = {}
        self.subscribers: set[asyncio.Queue] = set()

    def snapshot(self):
        return {"department": {"name": self.card.name, "display_name": self.card.display_name,
                                "description": self.card.description, "device_id": self.device_id},
                "connection": self.connection, "connection_message": self.connection_message,
                "tasks": list(self.tasks.values()), "approvals": self.approvals(),
                "files": file_inventory(self.card, self.policy)}

    def approvals(self):
        return [item for item, future in self.pending.values() if not future.done()]

    def emit(self, event):
        data = json.dumps(event, ensure_ascii=False)
        for queue in tuple(self.subscribers):
            if queue.full():
                # Slow clients reconnect and receive an authoritative snapshot.
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)
                self.subscribers.discard(queue)
            else:
                queue.put_nowait(data)

    def connection_changed(self, state, message):
        self.connection, self.connection_message = state, message
        self.emit({"type": "connection", "connection": state, "connection_message": message})

    def patch(self, run_id, **values):
        self.tasks[run_id].update(values)
        self.emit({"type": "task_patch", "id": run_id, "patch": values})

    def delta(self, run_id, delta):
        task = self.tasks[run_id]
        if "content" in delta:
            # Bound retained local replay; events still stream normally while connected.
            task["content"] = (task["content"] + delta["content"])[-160_000:]
        if event := delta.get("tool_event"):
            tools = task["tools"]
            existing = next((t for t in tools if t["id"] == event["id"]), None)
            tool = {**(existing or {}), **{k: v for k, v in event.items() if k != "type"},
                    "status": {"tool_start": "running", "tool_end": "complete", "tool_error": "error"}[event["type"]]}
            if existing:
                tools[tools.index(existing)] = tool
            else:
                tools.append(tool)
            result = tool.get("result") or {}
            if event["type"] == "tool_end" and isinstance(result.get("plan"), list):
                task["plans"][tool["agent"]] = result["plan"]
        if plan := delta.get("plan"):
            task["plans"][plan["agent"]] = plan["phases"]
        self.emit({"type": "delta", "id": run_id, "delta": delta})

    async def ask(self, run_id, request):
        approval_id = uuid4().hex
        item = {**request, "id": approval_id, "run_id": run_id,
                "expires_at": time.time() + self.approval_timeout}
        future = asyncio.get_running_loop().create_future()
        self.pending[approval_id] = item, future
        self.patch(run_id, status="waiting")
        self.emit({"type": "approvals", "approvals": self.approvals()})
        decision = "cancelled"
        try:
            try:
                approved = await asyncio.wait_for(future, self.approval_timeout)
                decision = "approved" if approved else "denied"
                return approved
            except TimeoutError:
                decision = "expired"
                return False
        finally:
            self.pending.pop(approval_id, None)
            self.emit({"type": "approvals", "approvals": self.approvals()})
            self.patch(run_id, status="running", last_approval={"kind": request["kind"], "decision": decision})

    def decide(self, approval_id, approved):
        pending = self.pending.get(approval_id)
        if not pending or pending[1].done() or pending[0]["expires_at"] <= time.time():
            raise HTTPException(409, "This request is no longer pending. Refreshing the approval queue.")
        pending[1].set_result(approved)

    async def answer(self, ws, run_id, task):
        # Retain the latest 20 tasks in local memory. Never evict active work.
        for old_id in list(self.tasks):
            if len(self.tasks) < 20:
                break
            if self.tasks[old_id]["status"] not in ("running", "waiting"):
                self.tasks.pop(old_id)
                self.emit({"type": "task_removed", "id": old_id})
        record = {"id": run_id, "task_id": task["task_id"], "question": task["question"],
                  "started_at": time.time(), "status": "running", "content": "", "tools": [],
                  "plans": {}, "departmentTasks": {}}
        self.tasks[run_id] = record
        self.emit({"type": "task", "task": record})

        async def ask(request):
            await ws.send(encode(EVENT, {"dispatch_id": run_id, "event": {"name": "approval_requested", "kind": request["kind"]}}))
            approved = await self.ask(run_id, request)
            await ws.send(encode(EVENT, {"dispatch_id": run_id, "event": {"name": "approval_decided", "kind": request["kind"], "approved": approved}}))
            return approved

        try:
            result = await run_department_task(self.graph, self.card, task, ask,
                                               callbacks=[LocalCallback(self, run_id)])
            result["device_id"] = self.device_id
            # Delivery is confirmed only after the hub WebSocket accepts the send.
            await ws.send(encode(RESULT, {"dispatch_id": run_id, "result": result}))
            self.patch(run_id, status=result["status"], result=result)
        except asyncio.CancelledError:
            self.patch(run_id, status="cancelled")
            raise
        except Exception as exc:
            self.patch(run_id, status="failed", error=f"Task failed: {exc.__class__.__name__}")
        finally:
            stopped = [{**tool, "status": "stopped"} if tool["status"] == "running" else tool
                       for tool in self.tasks[run_id]["tools"]]
            self.patch(run_id, tools=stopped)
            self.emit({"type": "files", "files": file_inventory(self.card, self.policy)})

    async def run(self):
        if self.graph is None:
            try:
                self.graph = build_department_graph(self.card, self.policy)
            except Exception as exc:
                self.connection_changed("rejected", f"Could not initialize the agent: {exc.__class__.__name__}")
                return
        while True:
            jobs = set()
            try:
                async with connect(self.hub_url, max_size=MAX_FRAME_BYTES, ping_interval=PING_INTERVAL_SECONDS,
                                   ping_timeout=PING_TIMEOUT_SECONDS, open_timeout=10) as ws:
                    await ws.send(encode(REGISTER, {"device_id": self.device_id, "department": self.card.name,
                                                   "capability": self.card.description}))
                    kind, ack = decode(await ws.recv())
                    if kind != REGISTER_ACK or not ack["ok"]:
                        self.connection_changed("rejected", str(ack.get("message") or "Registration rejected"))
                        return
                    if self.log_session:
                        self.log_session.rotate(f"[{self.card.name}] {self.card.display_name} on {self.device_id} · dashboard approvals")
                    self.connection_changed("connected", "Connected to coordinator")
                    async for raw in ws:
                        kind, payload = decode(raw)
                        if kind == TASK:
                            job = asyncio.create_task(self.answer(ws, payload["dispatch_id"], payload["task"]))
                            jobs.add(job)
                            job.add_done_callback(jobs.discard)
            except (OSError, WebSocketException, ProtocolError):
                pass
            finally:
                for job in jobs:
                    job.cancel()
                if jobs:
                    await asyncio.gather(*jobs, return_exceptions=True)
            self.connection_changed("disconnected", "Waiting for coordinator")
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)


class Decision(BaseModel):
    approved: StrictBool


def create_app(runtime, *, start_agent=True):
    @asynccontextmanager
    async def lifespan(app):
        worker = asyncio.create_task(runtime.run()) if start_agent else None
        try:
            yield
        finally:
            if worker:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker

    app = FastAPI(title="Department device API", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3001", "http://127.0.0.1:3001",
                        "tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"],
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Accept"])

    @app.get("/api/department")
    async def snapshot():
        return runtime.snapshot()

    @app.get("/api/department/files")
    async def files():
        return file_inventory(runtime.card, runtime.policy)

    @app.get("/api/department/events")
    async def events():
        async def stream():
            queue = asyncio.Queue(maxsize=256)
            runtime.subscribers.add(queue)
            try:
                yield {"data": json.dumps({"type": "snapshot", "state": runtime.snapshot()})}
                while True:
                    item = await queue.get()
                    if item is None:
                        return
                    yield {"data": item}
            finally:
                runtime.subscribers.discard(queue)
        return EventSourceResponse(stream(), ping=15, headers={"Cache-Control": "no-cache"})

    @app.post("/api/department/approvals/{approval_id}")
    async def approve(approval_id: str, decision: Decision):
        runtime.decide(approval_id, decision.approved)
        return {"ok": True}

    return app


def main():
    parser = argparse.ArgumentParser(description="Serve the local department client and agent")
    parser.add_argument("--department", required=True)
    parser.add_argument("--data-dir", default="")
    parser.add_argument("--id", default="")
    parser.add_argument("--hub", default=f"ws://{settings.hub_host}:{settings.hub_port}")
    parser.add_argument("--port", type=int, default=8101)
    args = parser.parse_args()
    session = capture(f"agent-{args.department}", "server.department")
    setup_logging(settings.log_level)
    card = load_card(args.data_dir or str(Path(DEVICES_DIR) / args.department))
    runtime = DepartmentRuntime(card, department_policy(card), args.id or f"pc-{card.name}", args.hub, log_session=session)
    uvicorn.run(create_app(runtime), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
