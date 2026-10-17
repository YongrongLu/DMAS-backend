"""Exercise the real graph and callback routing without models or devices."""

import asyncio
import json
from contextlib import suppress
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage

from core.agents import orchestrator
from core.agents.graph import build_graph
from server.callbacks import CompletionCallbackHandler
from server.main import create_app
from server.schemas import ChatCompletionRequest
from server.service import CompletionService


class FakeHub:
    def department_cards(self):
        return {d: {"device": d, "description": d} for d in ("sales", "customer", "product")}

    def online_departments(self):
        return {d: d for d in self.department_cards()}

    async def dispatch(self, task):
        await asyncio.sleep(0)
        return {**task, "status": "success", "summary": "An aggregate finding", "elapsed_seconds": 0}


class ScriptedModel(FakeListChatModel):
    def bind_tools(self, *args, **kwargs):
        return self


def app_with_graph(graph):
    app = create_app()
    app.state.completions = CompletionService(graph, FakeHub(), "test-model")
    return app


def payload():
    return {"model": "retail-rescue", "stream": True, "messages": [{"role": "user", "content": "Investigate sales"}]}


def unpack(response):
    lines = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
    assert lines[-1] == "[DONE]"
    return [json.loads(line) for line in lines[:-1]]


def test_real_graph_tools_departments_and_final_text(monkeypatch):
    replies = iter([
        AIMessage(content="", tool_calls=[
            {"name": "make_plan", "args": {"phases": [{"id": "p1", "title": "Investigate"}]}, "id": "plan-1"},
            {"name": "fanout_subagents", "args": {"tasks": [
                {"department": d, "question": "What changed?"} for d in FakeHub().department_cards()
            ]}, "id": "fanout-1"},
        ]),
        AIMessage(content="", tool_calls=[
            {"name": "edit_plan", "args": {"updates": [{"id": "p1", "status": "done"}]}, "id": "edit-1"},
            {"name": "end_orchestration", "args": {"response": "A summary"}, "id": "end-1"},
        ]),
    ])

    async def invoke(*args, **kwargs):
        return next(replies)

    monkeypatch.setattr(orchestrator, "invoke", invoke)
    monkeypatch.setattr(orchestrator, "chat_model", lambda **kw: ScriptedModel(responses=["Final report ✓"]))
    app = app_with_graph(build_graph())
    response = TestClient(app).post("/v1/chat/completions", json=payload())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    chunks = unpack(response)
    assert len({c["id"] for c in chunks}) == 1
    assert len({c["created"] for c in chunks}) == 1
    assert all(c["choices"][0]["index"] == 0 for c in chunks)
    assert all(c["choices"][0]["finish_reason"] is None for c in chunks[:-1])
    assert chunks[-1]["choices"][0] == {"index": 0, "delta": {}, "finish_reason": "stop"}
    deltas = [c["choices"][0]["delta"] for c in chunks]
    assert "".join(d.get("content", "") for d in deltas) == "Final report ✓"
    tools = [d["tool_event"] for d in deltas if "tool_event" in d]
    assert tools[0]["arguments"]["phases"][0]["title"] == "Investigate"
    final_tool = next(t for t in tools if t["name"] == "end_orchestration" and t["type"] == "tool_end")
    assert final_tool["result"]["plan"][0]["status"] == "done"
    plans = [d["plan"]["phases"] for d in deltas if "plan" in d]
    assert plans[0][0]["status"] == "pending"
    edited = next(t for t in tools if t["name"] == "edit_plan" and t["type"] == "tool_end")
    assert edited["result"]["plan"][0]["status"] == "done"
    assert plans[-1][0]["status"] == "done"
    assert [(t["id"], t["type"]) for t in tools] == [
        (id, type) for id in ("plan-1", "fanout-1", "edit-1", "end-1") for type in ("tool_start", "tool_end")
    ]
    progress = [d["workflow"] for d in deltas if "workflow" in d]
    assert len([e for e in progress if e["type"] == "department_start"]) == 3
    assert len([e for e in progress if e["type"] == "department_end"]) == 3
    assert not app.state.completions.lock.locked()


@pytest.mark.asyncio
async def test_callbacks_pair_concurrent_tools_and_hide_private_tokens():
    queue = asyncio.Queue()
    handler = CompletionCallbackHandler(queue)
    private, report, first, second = [uuid4() for _ in range(4)]
    await handler.on_chat_model_start({}, [[]], run_id=private, metadata={"langgraph_node": "orchestrator"})
    await handler.on_llm_new_token("PRIVATE", run_id=private)
    await handler.on_chat_model_start({}, [[]], run_id=report, metadata={"langgraph_node": "announce"})
    await handler.on_llm_new_token("Visible", run_id=report)
    await handler.on_tool_start({"name": "same_tool"}, "first", run_id=first)
    await handler.on_tool_start({"name": "same_tool"}, "second", run_id=second)
    await handler.on_tool_end("second result", run_id=second)
    await handler.on_tool_error(ValueError("first failed"), run_id=first)
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    assert "".join(e.content or "" for e in events) == "Visible"
    tools = [e.tool_event for e in events if e.tool_event]
    assert [(t.id, t.type) for t in tools] == [
        (str(first), "tool_start"), (str(second), "tool_start"),
        (str(second), "tool_end"), (str(first), "tool_error"),
    ]
    assert not handler._tools


@pytest.mark.asyncio
async def test_structured_plan_survives_preview_truncation():
    queue = asyncio.Queue()
    handler = CompletionCallbackHandler(queue)
    run_id = uuid4()
    phases = [{"id": f"p{i}", "title": "A detailed step " * 50, "status": "pending"} for i in range(8)]
    await handler.on_tool_start({"name": "make_plan"}, "{}", inputs={"phases": phases}, run_id=run_id)
    await handler.on_tool_end(json.dumps({"status": "ok", "plan": phases}), run_id=run_id)
    start, end = queue.get_nowait().tool_event, queue.get_nowait().tool_event
    assert len(start.arguments["phases"]) == 8
    assert end.output.endswith("…")
    assert len(end.result["plan"]) == 8
    assert end.result["plan"][-1]["id"] == "p7"


@pytest.mark.asyncio
@pytest.mark.parametrize("name,output", [
    ("bash", "exit code 2\nstdout:\nPartial result\nstderr:\nMissing file"),
    ("view_file", "Error: missing.csv is not a file"),
    ("load_skill", '{"status":"error","message":"Unavailable skill"}'),
])
async def test_returned_errors_are_rendered_as_tool_failures(name, output):
    queue = asyncio.Queue()
    handler = CompletionCallbackHandler(queue)
    run_id = uuid4()
    await handler.on_tool_start({"name": name}, "{}", run_id=run_id)
    await handler.on_tool_end(output, run_id=run_id)
    queue.get_nowait()
    event = queue.get_nowait().tool_event
    assert event.type == "tool_error"
    if name == "bash":
        assert event.result == {"exit_code": 2, "stdout": "Partial result", "stderr": "Missing file"}


@pytest.mark.asyncio
async def test_empty_report_writer_uses_graph_fallback_once():
    queue = asyncio.Queue()
    handler = CompletionCallbackHandler(queue)
    await handler.text("  \n")
    assert not handler.content_sent
    await handler.on_custom_event("report", {"text": "Coordinator fallback"}, run_id=uuid4())
    await handler.on_custom_event("report", {"text": "Coordinator fallback"}, run_id=uuid4())
    text = "".join(queue.get_nowait().content or "" for _ in range(queue.qsize()))
    assert text.strip() == "Coordinator fallback"


def test_validation_cors_and_terminal_error():
    class BrokenGraph:
        async def ainvoke(self, *args, **kwargs):
            raise RuntimeError("A test failure")

    app = app_with_graph(BrokenGraph())
    client = TestClient(app)
    assert client.post("/v1/chat/completions", json={**payload(), "stream": False}).status_code == 422
    assert client.post("/v1/chat/completions", json={**payload(), "messages": []}).status_code == 422
    assert client.post("/v1/chat/completions", json={**payload(), "messages": [{"role": "user", "content": "  "}]}).status_code == 422
    assert client.post("/v1/chat/completions", json={**payload(), "model": "unknown"}).status_code == 400
    for origin in ("http://localhost:3000", "tauri://localhost", "http://tauri.localhost"):
        response = client.options("/v1/chat/completions", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type",
        })
        assert response.headers["access-control-allow-origin"] == origin
    chunks = unpack(client.post("/v1/chat/completions", json=payload()))
    assert chunks[-1]["error"]["message"] == "A test failure"
    assert not any(c.get("choices", [{}])[0].get("finish_reason") == "stop" for c in chunks)
    assert not app.state.completions.lock.locked()


@pytest.mark.asyncio
async def test_disconnect_cancels_producer_and_releases_busy_slot():
    class WaitingGraph:
        def __init__(self):
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def ainvoke(self, *args, **kwargs):
            self.started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled.set()

    graph = WaitingGraph()
    service = CompletionService(graph, FakeHub(), "test-model")
    response = await service.open(ChatCompletionRequest(**payload()))
    iterator = response.body_iterator
    await anext(iterator)  # role
    await anext(iterator)  # planning
    waiting = asyncio.create_task(anext(iterator))
    await graph.started.wait()
    with pytest.raises(HTTPException) as exc:
        await service.open(ChatCompletionRequest(**payload()))
    assert exc.value.status_code == 409
    waiting.cancel()
    with suppress(asyncio.CancelledError):
        await waiting
    await iterator.aclose()
    assert graph.cancelled.is_set()
    assert not service.lock.locked()
    # Also release a reservation if a response is closed before iteration.
    second = await service.open(ChatCompletionRequest(**payload()))
    await second.background()
    assert not service.lock.locked()
