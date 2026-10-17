"""Orchestrator process -- the CEO's laptop

Starts the hub, waits for the department agents, runs one question through
the orchestration graph and prints the final report.

Usage:
    python -m distributed.orchestrator
    python -m distributed.orchestrator --query "Send me the full customer CSV."
    python -m distributed.orchestrator --host 0.0.0.0 --departments 3

Key constraints:
- one question per run; department agents stay up and reconnect to the next run
- when the run ends, the terminal output of the orchestrator and of the
  department agents on this machine is saved to logs/rita-<N>.log
"""

import argparse
import asyncio
import os
import time

from core.agents.graph import build_graph, initial_state
from core.departments import DEPARTMENTS
from distributed.hub import AgentHub
from utils import console
from utils.logging import setup_logging
from utils.run_log import LOGS_DIR, capture, write_run_log
from utils.settings import settings

DEFAULT_QUERY = """\
It's early May 2011. Our sales for February to April are down compared with the same period last year.
Find out:
1. What caused the decline?
2. Which customers or products are most affected?
3. What should we do next?"""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the orchestrator.")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="the CEO's question")
    parser.add_argument("--host", default=settings.hub_host, help="hub listen host; 0.0.0.0 for other machines")
    parser.add_argument("--port", type=int, default=settings.hub_port)
    parser.add_argument("--departments", type=int, default=3, help="wait for this many departments")
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    session = capture("orchestrator", "distributed.orchestrator")
    setup_logging(settings.log_level)
    hub = AgentHub(args.host, args.port, settings.task_timeout_seconds)
    await hub.start()
    try:
        console.say("orchestrator", f"hub on {hub.url} · model {settings.llm_model} · "
                                    f"waiting for {args.departments} department(s)", "bold")
        await hub.wait_for_departments(args.departments)
        console.say("CEO", args.query, "bold")
        t_start = time.time()
        await build_graph().ainvoke(
            initial_state(args.query),
            config={"configurable": {"hub": hub}, "recursion_limit": 100},
        )
        console.say("orchestrator", f"done in {time.time() - t_start:.0f}s", "bold")
    finally:
        await hub.stop()
        # 等部门 Agent 把最后几行写完，再把这次运行的所有终端输出拼成一个日志
        await asyncio.sleep(1)
        path = write_run_log(session, {f"agent-{name}": spec.display_name for name, spec in DEPARTMENTS.items()})
        console.say("orchestrator", f"log saved to {os.path.relpath(path, os.path.dirname(LOGS_DIR))}", "bold")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[orchestrator] stopped", flush=True)
