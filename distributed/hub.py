"""Agent hub -- the WebSocket server inside the orchestrator process

Department agents connect to it, register their department, and receive
tasks; the orchestrator graph dispatches through it.

Provides:
- AgentHub:     registry of online departments plus task dispatch

Key constraints:
- one online device per department; a second registration for the same
  department is rejected
- dispatch never raises: offline, disconnect and timeout all come back as a
  failed result, so the orchestrator can report the gap
- a disconnect fails every pending task of that device at once
"""

import asyncio
import time
import uuid

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from core.departments import DEPARTMENTS
from distributed.constants import MAX_FRAME_BYTES, PING_INTERVAL_SECONDS, PING_TIMEOUT_SECONDS, REGISTER_TIMEOUT_SECONDS
from distributed.protocol import REGISTER, REGISTER_ACK, RESULT, TASK, ProtocolError, decode, encode, failed_result
from utils import console
from utils.logging import get_logger

logger = get_logger(__name__)


class AgentHub:
    """Online department agents and task dispatch."""

    def __init__(self, host: str, port: int, task_timeout: float):
        self._host, self._port, self._task_timeout = host, port, task_timeout
        self._server = None
        # device_id -> {"ws", "department", "capability"}
        self._devices: dict[str, dict] = {}
        # dispatch_id -> (future, device_id)
        self._pending: dict[str, tuple[asyncio.Future, str]] = {}

    @property
    def url(self) -> str:
        return f"ws://{self._host}:{self._port}"

    async def start(self) -> None:
        """Start listening."""
        self._server = await serve(self._handle, self._host, self._port, max_size=MAX_FRAME_BYTES,
                                   ping_interval=PING_INTERVAL_SECONDS, ping_timeout=PING_TIMEOUT_SECONDS)

    async def stop(self) -> None:
        """Close every connection and stop listening."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    def online_departments(self) -> dict[str, str]:
        """department -> device_id of every online agent."""
        return {info["department"]: device for device, info in self._devices.items()}

    async def wait_for_departments(self, count: int) -> None:
        """Block until `count` departments are online."""
        while len(self._devices) < count:
            await asyncio.sleep(0.5)

    async def dispatch(self, task: dict) -> dict:
        """Send a task to its device and wait for the result; never raises."""
        device_id = task.get("device_id", "")
        device = self._devices.get(device_id)
        if device is None:
            return failed_result(task, "the device is offline")

        dispatch_id = uuid.uuid4().hex[:12]
        future = asyncio.get_running_loop().create_future()
        self._pending[dispatch_id] = (future, device_id)
        t_start = time.time()
        try:
            await device["ws"].send(encode(TASK, {"dispatch_id": dispatch_id, "task": task}))
            result = await asyncio.wait_for(future, timeout=self._task_timeout)
            return {**result, "device_id": device_id}
        except TimeoutError:
            return failed_result(task, f"no answer within {self._task_timeout:.0f}s", "timeout", time.time() - t_start)
        except (ConnectionClosed, ConnectionError):
            return failed_result(task, "the device disconnected during the task", "failed", time.time() - t_start)
        except Exception as exc:
            logger.error("dispatch_error", device_id=device_id, error=str(exc)[:300])
            return failed_result(task, f"{exc.__class__.__name__}: {exc}", "failed", time.time() - t_start)
        finally:
            self._pending.pop(dispatch_id, None)

    async def _handle(self, ws: ServerConnection) -> None:
        """Serve one agent connection from registration until it closes."""
        device_id = await self._register(ws)
        if device_id is None:
            return
        try:
            async for raw in ws:
                self._on_result(device_id, raw)
        except ConnectionClosed:
            pass
        finally:
            self._unregister(device_id)

    async def _register(self, ws: ServerConnection) -> str | None:
        """Validate the register frame and answer it; None when rejected."""
        try:
            msg_type, payload = decode(await asyncio.wait_for(ws.recv(), timeout=REGISTER_TIMEOUT_SECONDS))
        except (TimeoutError, ConnectionClosed, ProtocolError) as exc:
            logger.warning("register_failed", error=str(exc))
            return None

        device_id = str(payload.get("device_id", "")).strip()
        department = payload.get("department")
        reason = None
        if msg_type != REGISTER:
            reason = f"first message must be {REGISTER}"
        elif not device_id or device_id in self._devices:
            reason = f"device id {device_id!r} is empty or already online"
        elif department not in DEPARTMENTS:
            reason = f"department must be one of {sorted(DEPARTMENTS)}"
        elif department in self.online_departments():
            reason = f"the {department} department is already online on {self.online_departments()[department]}"
        if reason:
            await ws.send(encode(REGISTER_ACK, {"ok": False, "message": reason}))
            return None

        self._devices[device_id] = {"ws": ws, "department": department, "capability": payload["capability"]}
        await ws.send(encode(REGISTER_ACK, {"ok": True, "message": "registered"}))
        console.say("hub", f"+ {department} online @ {device_id} ({ws.remote_address[0]})", "green")
        return device_id

    def _on_result(self, device_id: str, raw) -> None:
        """Resolve the dispatch a result frame answers."""
        try:
            msg_type, payload = decode(raw)
        except ProtocolError as exc:
            logger.warning("bad_frame", device_id=device_id, error=str(exc))
            return
        pending = self._pending.get(payload["dispatch_id"]) if msg_type == RESULT else None
        if pending is None or pending[0].done():
            logger.warning("late_or_unexpected_frame", device_id=device_id, type=msg_type)
            return
        pending[0].set_result(payload["result"])

    def _unregister(self, device_id: str) -> None:
        """Forget a device and fail its pending tasks."""
        info = self._devices.pop(device_id, None)
        for future, owner in list(self._pending.values()):
            if owner == device_id and not future.done():
                future.set_exception(ConnectionError(device_id))
        if info:
            console.say("hub", f"- {info['department']} offline @ {device_id}", "red")
