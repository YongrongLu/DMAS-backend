"""Local department streaming and owner decisions, without a model server."""

import asyncio
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from core.agents.worker import graph as worker
from core.departments import DepartmentCard
from core.tools._kernel._access import AccessPolicy
from distributed.protocol import RESULT, decode
from server.department import DepartmentRuntime, create_app, file_inventory


@pytest.fixture
def runtime(tmp_path):
    for name in ("shared", "private", "workspace"):
        (tmp_path / name).mkdir()
    (tmp_path / "shared/data.csv").write_text("category,value\nGarden,42\n")
    (tmp_path / "private/costs.csv").write_text("LOCAL_SECRET,123\n")
    card = DepartmentCard("product", "Product Department", "Product analysis", str(tmp_path))
    policy = AccessPolicy("product", str(tmp_path / "workspace"), (str(tmp_path / "shared"),), (str(tmp_path),))
    return DepartmentRuntime(card, policy, "pc-product", "ws://127.0.0.1:1", approval_timeout=2)


def record(runtime, run_id="run-1"):
    runtime.tasks[run_id] = {"id": run_id, "status": "running", "content": "", "tools": [], "plans": {}}
    return run_id


@pytest.mark.asyncio
async def test_approval_is_exactly_once_and_false_is_denial(runtime):
    run_id = record(runtime)
    task = asyncio.create_task(runtime.ask(run_id, {"kind": "task", "task_id": "t1", "text": "Run?"}))
    await asyncio.sleep(0)
    approval = runtime.approvals()[0]
    runtime.decide(approval["id"], False)
    with pytest.raises(HTTPException) as duplicate:
        runtime.decide(approval["id"], True)
    assert duplicate.value.status_code == 409
    assert await task is False
    assert runtime.approvals() == []
    assert runtime.tasks[run_id]["last_approval"]["decision"] == "denied"


@pytest.mark.asyncio
async def test_timeout_and_disconnect_never_approve(runtime):
    run_id = record(runtime)
    runtime.approval_timeout = .01
    assert await runtime.ask(run_id, {"kind": "access", "task_id": "t1"}) is False
    assert runtime.tasks[run_id]["last_approval"]["decision"] == "expired"
    runtime.approval_timeout = 10
    pending = asyncio.create_task(runtime.ask(run_id, {"kind": "deliver", "task_id": "t1"}))
    await asyncio.sleep(0)
    old_id = runtime.approvals()[0]["id"]
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not runtime.pending
    with pytest.raises(HTTPException):
        runtime.decide(old_id, True)


@pytest.mark.asyncio
async def test_concurrent_requests_are_not_confused(runtime):
    a, b = record(runtime, "a"), record(runtime, "b")
    first = asyncio.create_task(runtime.ask(a, {"kind": "task", "task_id": "same"}))
    second = asyncio.create_task(runtime.ask(b, {"kind": "task", "task_id": "same"}))
    await asyncio.sleep(0)
    approvals = runtime.approvals()
    runtime.decide(approvals[1]["id"], True)
    assert await second is True
    assert not first.done()
    runtime.decide(approvals[0]["id"], False)
    assert await first is False


def test_inventory_does_not_follow_symlinks_or_read_contents(runtime, tmp_path):
    outside = tmp_path / "other"
    outside.mkdir()
    (outside / "hidden-secret.txt").write_text("DO NOT READ")
    (tmp_path / "workspace/escape").symlink_to(outside, target_is_directory=True)
    tree = file_inventory(runtime.card, runtime.policy)
    payload = json.dumps(tree)
    assert "data.csv" in payload and "costs.csv" in payload
    assert "LOCAL_SECRET" not in payload and "hidden-secret" not in payload and "escape" not in payload
    assert tree[1]["locked"] is True


def test_http_decisions_reject_strings_and_unknown_ids(runtime):
    with TestClient(create_app(runtime, start_agent=False)) as client:
        assert client.get("/api/department").json()["department"]["name"] == "product"
        assert client.post("/api/department/approvals/missing", json={"approved": "false"}).status_code == 422
        assert client.post("/api/department/approvals/missing", json={"approved": True}).status_code == 409
        preflight = client.options("/api/department/approvals/missing", headers={
            "Origin": "https://untrusted.example", "Access-Control-Request-Method": "POST"})
        assert preflight.status_code == 400
        for origin in ("http://localhost:3001", "tauri://localhost"):
            allowed = client.options("/api/department/approvals/missing", headers={
                "Origin": origin, "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type"})
            assert allowed.status_code == 200
            assert allowed.headers["access-control-allow-origin"] == origin


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, *args, **kwargs):
        return self


class Socket:
    def __init__(self):
        self.frames = []

    async def send(self, frame):
        self.frames.append(decode(frame))


async def run_with_decisions(runtime, decisions):
    socket = Socket()
    job = asyncio.create_task(runtime.answer(socket, "dispatch-1", {"task_id": "t1", "question": "Analyze margin"}))
    kinds = []
    async with asyncio.timeout(5):
        while not job.done():
            for approval in runtime.approvals():
                kinds.append(approval["kind"])
                runtime.decide(approval["id"], decisions.get(approval["kind"], False))
            await asyncio.sleep(.001)
        await job
    return socket, kinds


@pytest.mark.asyncio
async def test_real_graph_streams_tools_plan_and_local_text_with_three_owner_gates(runtime, monkeypatch):
    private = runtime.card.private_dir + "/costs.csv"
    model = ScriptedModel(responses=[
        AIMessage(content="", tool_calls=[
            {"name": "make_plan", "args": {"phases": [{"id": "p1", "title": "Analyze"}]}, "id": "plan"},
            {"name": "view_file", "args": {"path": private}, "id": "blocked"},
        ]),
        AIMessage(content="", tool_calls=[
            {"name": "view_file", "args": {"path": private}, "id": "read"},
            {"name": "edit_plan", "args": {"updates": [{"id": "p1", "status": "done"}]}, "id": "edit"},
        ]),
        AIMessage(content="Aggregate margin is healthy."),
    ])
    monkeypatch.setattr(worker, "chat_model", lambda: model)
    runtime.graph = worker.build_department_graph(runtime.card, runtime.policy)
    socket, kinds = await run_with_decisions(runtime, {"task": True, "access": True, "deliver": False})
    assert kinds == ["task", "access", "deliver"]
    task = runtime.tasks["dispatch-1"]
    assert task["plans"]["product"][0]["status"] == "done"
    assert task["content"] == "Aggregate margin is healthy."
    assert any(t["name"] == "view_file" and "LOCAL_SECRET" in t.get("output", "") for t in task["tools"])
    assert all(t["agent"] == "product" for t in task["tools"])
    assert task["status"] == "declined"
    assert "LOCAL_SECRET" not in json.dumps(socket.frames)
    final = [payload for kind, payload in socket.frames if kind == RESULT][0]["result"]
    assert final["egress"] == "withheld"
    assert "healthy" not in final["summary"]


@pytest.mark.asyncio
async def test_declining_intake_does_not_call_model(runtime, monkeypatch):
    model = ScriptedModel(responses=[AIMessage(content="must not run")])
    monkeypatch.setattr(worker, "chat_model", lambda: model)
    runtime.graph = worker.build_department_graph(runtime.card, runtime.policy)
    socket, kinds = await run_with_decisions(runtime, {"task": False})
    assert kinds == ["task"]
    assert runtime.tasks["dispatch-1"]["content"] == ""
    assert runtime.tasks["dispatch-1"]["tools"] == []
    assert socket.frames[-1][1]["result"]["status"] == "declined"


@pytest.mark.asyncio
async def test_sse_reconnect_snapshot_and_slow_subscriber_recovery(runtime):
    record(runtime)
    app = create_app(runtime, start_agent=False)
    endpoint = next(route.endpoint for route in app.routes if route.path == "/api/department/events")
    response = await endpoint()
    stream = response.body_iterator
    first = json.loads((await anext(stream))["data"])
    assert first["type"] == "snapshot"
    assert first["state"]["tasks"][0]["id"] == "run-1"
    runtime.delta("run-1", {"content": "Hello"})
    assert json.loads((await anext(stream))["data"])["delta"]["content"] == "Hello"
    await stream.aclose()
    assert not runtime.subscribers
    slow = asyncio.Queue(maxsize=1)
    runtime.subscribers.add(slow)
    runtime.emit({"type": "files", "files": []})
    runtime.emit({"type": "files", "files": []})
    assert await slow.get() is None
    assert slow not in runtime.subscribers
    assert runtime.snapshot()["tasks"][0]["content"] == "Hello"
