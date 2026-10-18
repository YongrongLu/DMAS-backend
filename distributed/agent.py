"""Department agent process -- runs on the department's own device

Connects to the orchestrator's hub, registers its department, and answers
every task with the local department graph over the local data file. Only
the conclusion is sent back.

Usage:
    python -m distributed.agent --department sales
    python -m distributed.agent --department customer --hub ws://100.64.0.1:8800
    python -m distributed.agent --department product --data-dir /path/to/product --id laptop-3

Key constraints:
- the data file never leaves this process; the hub only sees questions and conclusions
- tasks run concurrently; losing the hub cancels them (the hub has already
  reported them as failed) and the process reconnects
- the person at this device approves every task, any opening of private/ and
  every delivery (distributed/approval.py); each pause is reported to the hub
  as an event so the orchestrator can show who it is waiting for
"""

import argparse
import asyncio
import os

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from core.agents.worker.graph import build_department_graph, run_department_task
from core.departments import DEVICES_DIR, load_card
from core.tools._kernel._access import department_policy
from distributed.constants import MAX_FRAME_BYTES, PING_INTERVAL_SECONDS, PING_TIMEOUT_SECONDS, RECONNECT_DELAY_SECONDS
from distributed.approval import ask_owner
from distributed.protocol import EVENT, REGISTER, REGISTER_ACK, RESULT, TASK, ProtocolError, decode, encode
from utils import console
from utils.logging import get_logger, setup_logging
from utils.run_log import capture
from utils.settings import settings

logger = get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one department agent.")
    parser.add_argument("--department", required=True, help="department folder name under data/devices/")
    parser.add_argument("--data-dir", default="", help="the department folder with department.json (default: data/devices/<department>)")
    parser.add_argument("--hub", default=f"ws://{settings.hub_host}:{settings.hub_port}", help="hub url")
    parser.add_argument("--id", default="", help="device id shown to the orchestrator (default: pc-<department>)")
    return parser.parse_args()


async def _answer(ws: ClientConnection, graph, spec, device_id: str, dispatch_id: str, task: dict) -> None:
    """Run one task and send its result."""
    tag = f"{spec.name} · {task['task_id']}"
    console.say(tag, f"question: {console.preview(task['question'], 400)}", "bold")

    async def notify(event: dict) -> None:
        try:
            await ws.send(encode(EVENT, {"dispatch_id": dispatch_id, "event": event}))
        except ConnectionClosed:
            pass

    async def ask(request: dict) -> bool:
        await notify({"name": "approval_requested", "kind": request["kind"]})
        approved = await ask_owner(spec.name, request)
        await notify({"name": "approval_decided", "kind": request["kind"], "approved": approved})
        return approved

    result = await run_department_task(graph, spec, task, ask)
    result["device_id"] = device_id
    color = {"success": "green", "declined": "yellow"}.get(result["status"], "red")
    console.block(f"{tag} · {result['status']} in {result['elapsed_seconds']}s · sent to the orchestrator",
                  result["summary"].splitlines()[:40], color)
    try:
        await ws.send(encode(RESULT, {"dispatch_id": dispatch_id, "result": result}))
    except ConnectionClosed:
        logger.warning("result_not_sent", task_id=task["task_id"])


async def _serve(ws: ClientConnection, graph, spec, device_id: str) -> None:
    """Receive tasks until the connection closes."""
    running: set[asyncio.Task] = set()
    try:
        async for raw in ws:
            try:
                msg_type, payload = decode(raw)
            except ProtocolError as exc:
                logger.warning("bad_frame", error=str(exc))
                continue
            if msg_type != TASK:
                continue
            job = asyncio.create_task(_answer(ws, graph, spec, device_id, payload["dispatch_id"], payload["task"]))
            running.add(job)
            job.add_done_callback(running.discard)
    finally:
        jobs = list(running)
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)


async def main() -> None:
    args = _parse_args()
    # 先接管终端输出再配置日志：structlog 只在配置时绑定一次 stderr
    session = capture(f"agent-{args.department}", "distributed.agent")
    setup_logging(settings.log_level)
    spec = load_card(args.data_dir or os.path.join(DEVICES_DIR, args.department))
    policy = department_policy(spec)
    device_id = args.id or f"pc-{spec.name}"
    graph = build_department_graph(spec, policy)
    banner = (f"{spec.display_name} agent on {device_id} · data {spec.shared_dir} (read-only) · "
              f"workspace {policy.workspace} · model {settings.llm_model} · approvals {settings.approval_mode}")
    console.say(spec.name, banner, "bold")

    identity = {"device_id": device_id, "department": spec.name, "capability": spec.description}
    waiting = False
    while True:
        try:
            async with connect(args.hub, max_size=MAX_FRAME_BYTES, ping_interval=PING_INTERVAL_SECONDS,
                               ping_timeout=PING_TIMEOUT_SECONDS) as ws:
                await ws.send(encode(REGISTER, identity))
                msg_type, ack = decode(await ws.recv())
                if msg_type != REGISTER_ACK or not ack["ok"]:
                    raise SystemExit(f"registration rejected: {ack.get('message')}")
                # 每连上一次 orchestrator 就开一段新记录，跑完后由 orchestrator 拼进 logs/rita-<N>.log
                session.rotate(f"[{spec.name}] {banner}")
                console.say(spec.name, f"connected to {args.hub}", "green")
                waiting = False
                await _serve(ws, graph, spec, device_id)
        except (OSError, WebSocketException, ProtocolError) as exc:
            if not waiting:
                console.say(spec.name, f"waiting for the hub at {args.hub} ({exc.__class__.__name__})", "grey")
                waiting = True
        await asyncio.sleep(RECONNECT_DELAY_SECONDS)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[agent] stopped", flush=True)
