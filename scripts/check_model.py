"""Check that the model endpoint in .env works for our agents, in about a minute

Runs four checks against LLM_BASE_URL / LLM_MODEL with the real prompts and
tool definitions of this project:

1. models:          the endpoint answers and serves LLM_MODEL
2. chat:            a plain reply comes back, without leaked <think> text
3. orchestrator:    the model calls fanout_subagents with arguments our tool runner accepts
4. department:      the model calls shell_executor with a skill command, and the skill runs

Usage:
    ./.venv/bin/python scripts/check_model.py
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from openai import OpenAI  # noqa: E402

from core.agents.model import chat_model  # noqa: E402
from core.departments import get_department  # noqa: E402
from core.prompts.system_prompt_department import render_department_prompt  # noqa: E402
from core.prompts.system_prompt_orchestrator import render_orchestrator_prompt, render_snapshot  # noqa: E402
from core.tools._kernel.constants import PROJECT_ROOT  # noqa: E402
from core.tools.bundles.department import build_department_tools  # noqa: E402
from core.tools.bundles.orchestrator import ORCHESTRATOR_TOOL_SPECS, run_orchestrator_tool  # noqa: E402
from utils.settings import settings  # noqa: E402

COMMAND = ("python skills/period-comparison/scripts/compare.py --metric revenue "
           "--period-a 2010-02:2010-04 --period-b 2011-02:2011-04")


def report(name: str, ok: bool, detail: str, t_start: float) -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {name:<13} {time.time() - t_start:5.1f}s  {detail}", flush=True)
    return ok


def check_models() -> bool:
    t = time.time()
    try:
        ids = [m.id for m in OpenAI(api_key=settings.llm_api_key or "not-set", base_url=settings.llm_base_url).models.list().data]
    except Exception as exc:
        return report("models", False, f"cannot reach {settings.llm_base_url}: {exc}", t)
    return report("models", settings.llm_model in ids, f"served: {ids}; LLM_MODEL={settings.llm_model}", t)


async def check_chat() -> bool:
    t = time.time()
    reply = await chat_model().ainvoke([HumanMessage("Reply with exactly: OK")])
    text = str(reply.content)
    leaked = "<think>" in text or "</think>" in text
    return report("chat", bool(text.strip()) and not leaked,
                  "reasoning text leaked into the reply: start vLLM with --reasoning-parser" if leaked
                  else f"reply: {text.strip()[:80]!r}", t)


async def check_orchestrator() -> bool:
    t = time.time()
    online = {"sales": "pc-sales", "customer": "pc-customer", "product": "pc-product"}
    messages = [
        SystemMessage(render_orchestrator_prompt()),
        HumanMessage("Ask the sales department how revenue and orders changed between Feb-Apr 2010 and "
                     "Feb-Apr 2011. Skip the plan and call fanout_subagents now."),
        HumanMessage(render_snapshot([], 0, 14, online)),
    ]
    reply = await chat_model().bind_tools(ORCHESTRATOR_TOOL_SPECS).ainvoke(messages)
    calls = [c for c in reply.tool_calls if c["name"] == "fanout_subagents"]
    if not calls:
        return report("orchestrator", False, f"no fanout_subagents call (tool calls: {[c['name'] for c in reply.tool_calls]}, "
                      f"text: {str(reply.content)[:120]!r}); check --enable-auto-tool-choice and --tool-call-parser", t)
    work = {"plan": [], "round_tasks": [], "round": 0, "response": ""}
    result = json.loads(run_orchestrator_tool("fanout_subagents", calls[0]["args"], work, online))
    return report("orchestrator", result["status"] == "ok", result["message"], t)


async def check_department() -> bool:
    t = time.time()
    spec = get_department("sales")
    tools = build_department_tools(spec, os.path.join(PROJECT_ROOT, "data", "devices", "sales", "shared", spec.csv_name))
    messages = [SystemMessage(render_department_prompt(spec)),
                HumanMessage(f"Run exactly this command with shell_executor and nothing else: {COMMAND}")]
    reply = await chat_model().bind_tools(tools).ainvoke(messages)
    calls = [c for c in reply.tool_calls if c["name"] == "shell_executor"]
    if not calls:
        return report("department", False, f"no shell_executor call (tool calls: {[c['name'] for c in reply.tool_calls]})", t)
    result = json.loads(await tools[1].ainvoke(calls[0]["args"]))
    return report("department", result["status"] == "ok",
                  f"command: {calls[0]['args'].get('command', '')[:90]} -> {result['status']}", t)


async def main() -> None:
    print(f"endpoint {settings.llm_base_url} · model {settings.llm_model}\n", flush=True)
    if not check_models():
        raise SystemExit(1)
    results = [await check_chat(), await check_orchestrator(), await check_department()]
    print("\nall checks passed: run the four processes" if all(results) else "\nsome checks failed: see above")


if __name__ == "__main__":
    asyncio.run(main())
