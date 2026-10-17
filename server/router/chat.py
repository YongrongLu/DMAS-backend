from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from server.schemas import ChatCompletionRequest

router = APIRouter()


@router.post("/v1/chat/completions", response_class=StreamingResponse, tags=["Chat"])
async def chat_completion(body: ChatCompletionRequest, request: Request):
    """Stream a full agent run, including tool execution and department progress."""
    return await request.app.state.completions.open(body)


@router.get("/api/health", tags=["Status"])
async def health(request: Request):
    service = request.app.state.completions
    return {"ok": True, "model": service.model, "busy": service.lock.locked()}


@router.get("/api/departments", tags=["Status"])
async def departments(request: Request):
    return request.app.state.completions.hub.department_cards()
