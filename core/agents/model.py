"""Chat model access shared by every agent

Provides:
- chat_model:       the configured OpenAI-compatible chat model (cached)
- invoke:           call a model with retries on transient errors and one resend on an empty or cut-off reply

Key constraints:
- one endpoint for all agents (settings.llm_*); the orchestrator and the
  departments differ in prompts and tools, not in model
- thinking is only sent when set, as chat_template_kwargs, which is how vLLM
  toggles the reasoning of Qwen3 and Nemotron; the report writer turns it off
  because a long reasoning pass can use the whole token budget and leave no report
- thinking counts against max_tokens: a reply cut off at the limit
  (finish_reason "length") has a broken tool call or half a thought, so it
  is resent like an empty one instead of being used
"""

import asyncio
from functools import lru_cache

import httpx
import openai
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from utils.logging import get_logger
from utils.settings import settings

logger = get_logger(__name__)

MAX_RETRIES = 3
RETRYABLE = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
    httpx.TransportError,
)


@lru_cache(maxsize=4)
def chat_model(thinking: bool | None = None) -> ChatOpenAI:
    """The chat model every agent uses.

    Args:
        thinking:   override settings.llm_enable_thinking for this caller, e.g.
                    False for the report writer; None keeps the setting.
    """
    if thinking is None:
        thinking = settings.llm_enable_thinking
    extra_body = None
    if thinking is not None:
        extra_body = {"chat_template_kwargs": {"enable_thinking": thinking}}
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key or "not-set",
        base_url=settings.llm_base_url,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        extra_body=extra_body,
        # 流式调用：ainvoke 内部也会逐 token 触发 on_llm_new_token，SSE 桥才能把 token 推给前端
        streaming=True,
        stream_usage=True,
    )


def _is_empty(message: AIMessage) -> bool:
    """No tool call and no text."""
    return not message.tool_calls and not str(message.content or "").strip()


def _is_cut_off(message: AIMessage) -> bool:
    """Stopped at max_tokens, usually in the middle of thinking or of a tool call."""
    return (message.response_metadata or {}).get("finish_reason") == "length"


async def invoke(model, messages: list, *, role: str, config=None) -> AIMessage:
    """Call the model with retries.

    Args:
        model:      a chat model, possibly with tools bound.
        messages:   the request.
        role:       who is calling, for logs.
        config:     the node's RunnableConfig, so callbacks (e.g. the SSE bridge) see the call.

    Raises:
        the last transient error after MAX_RETRIES retries, or RuntimeError
        when the model answers empty or cut off twice.
    """
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await model.ainvoke(messages, config=config)
            if not _is_empty(response) and not _is_cut_off(response):
                return response
            problem = "cut off at max_tokens" if _is_cut_off(response) else "empty"
            logger.warning("llm_bad_response", role=role, problem=problem, attempt=attempt + 1)
            if attempt >= 1:
                raise RuntimeError(f"model response was {problem} twice (role={role}); "
                                   "raise LLM_MAX_TOKENS or set LLM_ENABLE_THINKING=false")
        except RETRYABLE as exc:
            if attempt == MAX_RETRIES:
                raise
            delay = 2 ** attempt
            logger.warning("llm_retry", role=role, attempt=attempt + 1, delay=delay, error=str(exc)[:200])
            await asyncio.sleep(delay)
    raise RuntimeError(f"model call failed (role={role})")
