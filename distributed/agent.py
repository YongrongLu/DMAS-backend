"""Department agent process -- runs on the department's own device

Connects to the orchestrator's hub, registers its department, and answers
every task with the local department graph over the local data file. Only
the conclusion is sent back.

Usage:
    python -m distributed.agent --department sales
    python -m distributed.agent --department customer --hub ws://100.64.0.1:8800
    python -m distributed.agent --department product --data /path/to/product_data.csv --id laptop-3

Key constraints:
- the data file never leaves this process; the hub only sees questions and conclusions
- tasks run concurrently; losing the hub cancels them (the hub has already
  reported them as failed) and the process reconnects
"""

import argparse
import asyncio
import os

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from core.agents.worker.graph import build_department_graph, run_department_task
from core.departments import DEPARTMENTS, get_department
from core.tools._kernel.constants import PROJECT_ROOT
from distributed.constants import MAX_FRAME_BYTES, PING_INTERVAL_SECONDS, PING_TIMEOUT_SECONDS, RECONNECT_DELAY_SECONDS
from distributed.protocol import REGISTER, REGISTER_ACK, RESULT, TASK, ProtocolError, decode, encode
from utils import console
from utils.logging import get_logger, setup_logging
from utils.run_log import capture
from utils.settings import settings

logger = get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one department agent.")
    parser.add_argument("--department", required=True, choices=sorted(DEPARTMENTS))
    parser.add_argument("--data", default="", help="the department view (default: data/devices/<department>/shared/...)")
    parser.add_argument("--hub", default=f"ws://{settings.hub_host}:{settings.hub_port}", help="hub url")
    parser.add_argument("--id", default="", help="device id shown to the orchestrator (default: pc-<department>)")
    return parser.parse_args()


async def _answer(ws: ClientConnection, graph, spec, device_id: str, dispatch_id: str, task: dict) -> None:
    """Run one task and send its result."""
    tag = f"{spec.name} · {task['task_id']}"
    console.say(tag, f"question: {console.preview(task['question'], 400)}", "bold")
    result = await run_department_task(graph, spec, task)
    result["device_id"] = device_id
    console.block(f"{tag} · {result['status']} in {result['elapsed_seconds']}s · sent to the orchestrator",
                  result["summary"].splitlines()[:40], "green" if result["status"] == "success" else "red")
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
        for job in running:
            job.cancel()


async def main() -> None:
    args = _parse_args()
    # 先接管终端输出再配置日志：structlog 只在配置时绑定一次 stderr
    session = capture(f"agent-{args.department}", "distributed.agent")
    setup_logging(settings.log_level)
    spec = get_department(args.department)
    data_path = os.path.abspath(args.data or os.path.join(PROJECT_ROOT, "data", "devices", spec.name, "shared", spec.csv_name))
    if not os.path.isfile(data_path):
        raise SystemExit(f"data file not found: {data_path}")
    device_id = args.id or f"pc-{spec.name}"
    graph = build_department_graph(spec, data_path)
    banner = f"{spec.display_name} agent on {device_id} · data {data_path} · model {settings.llm_model}"
    console.say(spec.name, banner, "bold")

    identity = {"device_id": device_id, "department": spec.name, "capability": spec.capability}
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
