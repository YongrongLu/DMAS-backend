"""Run lifetime, backpressure, heartbeats, and disconnect cancellation."""

import asyncio
import json
import logging
import time
from contextlib import suppress
from uuid import uuid4

import anyio
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from starlette.background import BackgroundTask

from core.agents.graph import initial_state
from server.callbacks import CompletionCallbackHandler
from server.schemas import ChatCompletionRequest, Choice, CompletionChunk, Delta, WorkflowEvent, sse_data

logger = logging.getLogger(__name__)
_END = object()


class CompletionService:
    def __init__(self, graph, hub, model: str):
        self.graph, self.hub, self.model = graph, hub, model
        self.lock = asyncio.Lock()

    async def open(self, body: ChatCompletionRequest) -> StreamingResponse:
        if body.model not in ("retail-rescue", self.model):
            raise HTTPException(400, "Unknown model; use retail-rescue or the configured LLM_MODEL")
        if self.lock.locked():
            raise HTTPException(409, "Another run is in progress. Try again after it finishes.")
        await self.lock.acquire()
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        callback = CompletionCallbackHandler(queue)
        completion_id, created = f"chatcmpl-{uuid4().hex}", int(time.time())
        task = None
        closed = False

        async def close():
            nonlocal closed
            if closed:
                return
            closed = True
            with anyio.CancelScope(shield=True):
                try:
                    if task is not None:
                        task.cancel()
                        with suppress(asyncio.CancelledError):
                            await task
                finally:
                    self.lock.release()

        def frame(delta: Delta, finish_reason=None):
            return sse_data(CompletionChunk(
                id=completion_id, created=created, model=self.model,
                choices=[Choice(delta=delta, finish_reason=finish_reason)],
            ))

        async def produce():
            try:
                state = initial_state(body.messages[-1].content.strip())
                state["messages"] = [
                    HumanMessage(m.content) if m.role == "user" else AIMessage(m.content)
                    for m in body.messages
                ]
                final = await self.graph.ainvoke(state, config={
                    "configurable": {"hub": self.hub, "run_id": completion_id},
                    "callbacks": [callback], "recursion_limit": 100,
                })
                if not callback.content_sent:
                    await callback.text(final.get("report", ""))
                await queue.put(_END)
            except Exception as exc:
                logger.exception("Orchestration failed: %s", completion_id)
                await queue.put({"error": {"type": "orchestration_error", "message": str(exc)[:1000]}})

        async def frames():
            nonlocal task
            try:
                yield frame(Delta(role="assistant"))
                yield frame(Delta(workflow=WorkflowEvent(type="phase", phase="planning")))
                task = asyncio.create_task(produce(), name=completion_id)
                while True:
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    if item is _END:
                        yield frame(Delta(), "stop")
                        break
                    if isinstance(item, dict):
                        yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                        break
                    yield frame(item)
                yield "data: [DONE]\n\n"
            finally:
                await close()

        return StreamingResponse(
            frames(), media_type="text/event-stream", background=BackgroundTask(close),
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
