# Chat API

Run from the `distributed-mas-demo` root with its existing Python environment:

```bash
.venv/bin/python -m server.main
```

HTTP listens on `127.0.0.1:8000`. The same process hosts the existing AgentHub
on `HUB_HOST:HUB_PORT` (defaults to `127.0.0.1:8800`). Model settings still come
from the backend `.env`. This replaces `python -m distributed.server` when
using the new frontend; run one entry point at a time because they share the hub port.

For agents on Tailscale, bind the hub to the main machine's Tailscale IP:

```bash
.venv/bin/python -m server.main --hub-host <main-machine-tailscale-ip>
```

The frontend can stay on the main machine and use localhost for HTTP. If the
frontend also runs remotely, set `--host <main-machine-tailscale-ip>`, configure
its `NEXT_PUBLIC_API_BASE_URL`, and add its origin to the comma-separated
`CORS_ORIGINS` environment variable. Default origins cover the local web UI
and Tauri. No HTTP authentication is implemented; keep this service on the
intended local/private network.

## Routes

- `POST /v1/chat/completions`: one full orchestration over SSE.
- `GET /api/health`: model name and whether a run is active.
- `GET /api/departments`: the hub's current department registrations.
- `GET /docs`: FastAPI's interactive request documentation.

```bash
curl -N http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"retail-rescue","stream":true,"messages":[{"role":"user","content":"Why are sales declining?"}]}'
```

`model` may be `retail-rescue` or the configured `LLM_MODEL`; it does not change
the configured upstream provider. `stream` must be `true`. `messages` accepts
user/assistant text history and must end with a non-empty user message. The
coordinator receives that history; the latest question starts a fresh graph run.
There is no conversation database or automatic reconnection/replay.

## SSE contract

Text uses the [OpenAI Chat Completions streaming envelope](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events).
Each frame is `data: <JSON>\n\n`. A response keeps the same `id`, `created`,
and `model` throughout. `index: 0` identifies the single choice, not a frame counter.

```json
{"id":"chatcmpl-…","object":"chat.completion.chunk","created":1792240000,"model":"configured-model","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}
```

Subsequent `delta` payloads:

| Payload | Meaning |
| --- | --- |
| `{"content":"Here is…"}` | Append text from the final report (`announce`). |
| `{"tool_event":{"type":"tool_start","id":"call-1","name":"make_plan","agent":"orchestrator","input":"…"}}` | Show a running tool. |
| `{"tool_event":{"type":"tool_end","id":"call-1","name":"make_plan","agent":"orchestrator","output":"…"}}` | Complete that tool. |
| `{"tool_event":{"type":"tool_error","id":"call-1","name":"make_plan","agent":"orchestrator","error":"…"}}` | Mark that tool as failed. The graph may recover and continue. |
| `{"workflow":{"type":"phase","phase":"planning"}}` | Coordinator phase: `planning`, `merging`, or `reporting`. |
| `{"workflow":{"type":"department_start","task_id":"r1-sales","department":"sales"}}` | Show the department node and spinner. |
| `{"workflow":{"type":"department_end","task_id":"r1-sales","department":"sales","status":"success"}}` | Return/collapse the matching node; other statuses represent failure. |
| `{"plan":{"agent":"orchestrator","phases":[{"id":"p1","title":"Compare sales","status":"done"}]}}` | Replace the agent's full plan snapshot. An empty `phases` list clears it. |

`delta.tool_event`, `delta.plan`, and `delta.workflow` are application extensions, not standard
OpenAI fields. They describe tools already executed by the server. They are
different from OpenAI `delta.tool_calls`, which asks a client to execute tools.
Pair tools by `id`, and departments by `task_id`, including across multiple rounds.
Tool events additionally include `arguments` (parsed inputs) and `result`
(parsed JSON results, or Bash `exit_code`/`stdout`/`stderr` fields). Individual
strings are capped without breaking the JSON shape, so plan phases and task
lists remain renderable even when the legacy text preview is truncated.
Nonzero Bash exits, returned error objects, and file access errors emit
`tool_error`. The final handoff emits the completed plan snapshot as well, and
the successful `end_orchestration` tool result also includes its full `plan`.
Tool input/output text previews are capped at 2,000 characters. Department raw data
and intermediate coordinator model tokens are not streamed as chat content.

The coordinator currently exposes plan, fanout, file, and handoff tools.
Bash and skill tools execute on department machines; the hub currently relays
department results rather than internal tool traces. Adding their UI renderers
does not change that transport or the department egress policy.

Successful termination:

```text
data: {"id":"chatcmpl-…","object":"chat.completion.chunk","created":1792240000,"model":"configured-model","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]

```

Before the stream starts, invalid requests return 422, an unknown model returns
400, and a concurrent run returns 409. After headers have been sent, an
unrecoverable run failure sends `data: {"error":{"type":"orchestration_error","message":"…"}}`
followed by `[DONE]`, without a successful `finish_reason`. Idle streams send
SSE comments every 15 seconds. Each request has a bounded queue and its own
`CompletionCallbackHandler`, based on LangChain's
[AsyncCallbackHandler](https://reference.langchain.com/python/langchain-core/callbacks/base/AsyncCallbackHandler).

Disconnecting (including the frontend Stop button) cancels the coordinator graph,
awaits cleanup, and frees the run slot. The current device protocol has no remote
cancel command, so a department may finish work it already received.

## Verify

```bash
.venv/bin/python -m pytest tests/test_chat_api.py -q
```

Tests use the real graph and LangChain callbacks with fake model/device
responses. They exercise tool pairing, department fanout, text streaming,
request validation, errors, CORS, concurrency, and cancellation without LLM calls.
