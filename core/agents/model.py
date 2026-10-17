"""Chat model access shared by every agent

Provides:
- chat_model:       the configured OpenAI-compatible chat model (cached)
- invoke:           call a model with retries on transient errors and one resend on an empty reply

Key constraints:
- one endpoint for all agents (settings.llm_*); the orchestrator and the
  departments differ in prompts and tools, not in model
- thinking is only sent when set, as chat_template_kwargs, which is how vLLM
  toggles Nemotron's reasoning; the report writer turns it off because a long
  reasoning pass can use the whole token budget and leave no report
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
    )


def _is_empty(message: AIMessage) -> bool:
    """No tool call and no text."""
    return not message.tool_calls and not str(message.content or "").strip()


async def invoke(model, messages: list, *, role: str) -> AIMessage:
    """Call the model with retries.

    Args:
        model:      a chat model, possibly with tools bound.
        messages:   the request.
        role:       who is calling, for logs.

    Raises:
        the last transient error after MAX_RETRIES retries, or RuntimeError
        when the model answers empty twice.
    """
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await model.ainvoke(messages)
            if not _is_empty(response):
                return response
            logger.warning("llm_empty_response", role=role, attempt=attempt + 1)
            if attempt >= 1:
                raise RuntimeError(f"model returned an empty response twice (role={role})")
        except RETRYABLE as exc:
            if attempt == MAX_RETRIES:
                raise
            delay = 2 ** attempt
            logger.warning("llm_retry", role=role, attempt=attempt + 1, delay=delay, error=str(exc)[:200])
            await asyncio.sleep(delay)
    raise RuntimeError(f"model call failed (role={role})")
