"""Run from the backend root: python -m server.main [--host HOST --port PORT]."""

import argparse
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.agents.graph import build_graph
from distributed.hub import AgentHub
from server.router.chat import router
from server.service import CompletionService
from utils.logging import setup_logging
from utils.settings import settings


def create_app(*, hub_host=None, hub_port=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging(settings.log_level)
        hub = AgentHub(hub_host or settings.hub_host,
                       hub_port if hub_port is not None else settings.hub_port,
                       settings.task_timeout_seconds)
        await hub.start()
        app.state.completions = CompletionService(build_graph(), hub, settings.llm_model)
        try:
            yield
        finally:
            await hub.stop()

    app = FastAPI(title="Retail Rescue · Chat API", version="0.1.0", lifespan=lifespan)
    origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,tauri://localhost,http://tauri.localhost,https://tauri.localhost")
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in origins.split(",") if o.strip()],
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Accept"])
    app.include_router(router)
    return app


app = create_app()


def main():
    parser = argparse.ArgumentParser(description="Serve Chat Completions over SSE")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--hub-host", default=settings.hub_host)
    parser.add_argument("--hub-port", type=int, default=settings.hub_port)
    args = parser.parse_args()
    uvicorn.run(create_app(hub_host=args.hub_host, hub_port=args.hub_port), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
