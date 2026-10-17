# Distributed MAS demo

Retail Rescue coordinates Sales, Customer, and Product agents through a WebSocket
AgentHub. Each department works on its own machine; the main machine combines
their returned findings into a report.

The frontend's FastAPI/SSE interface lives in [`server/`](server/README.md).
From this directory, start it with:

```bash
.venv/bin/python -m server.main
```

The API listens on `http://localhost:8000`, with interactive documentation at
`http://localhost:8000/docs`. The hub listens on the configured `HUB_HOST:HUB_PORT`.
See the server guide for the Chat Completions event contract, Tailscale setup,
and test commands.
