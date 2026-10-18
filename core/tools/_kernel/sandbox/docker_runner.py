"""Offline Docker execution for xyz-1's workspace Bash tool.

Only the workspace is writable. Read roots come from the active AccessPolicy,
including private data only after the existing task approval grants it.
"""
import asyncio
import os
from pathlib import Path, PureWindowsPath
import shutil
import uuid

from utils.settings import settings

MAX_STREAM_BYTES = 65536


class SandboxError(RuntimeError):
    """A diagnostic safe to return without host Docker credentials or output."""


def container_path(path: str) -> str:
    """Keep relative paths working across mounts, including Windows drive paths."""
    windows = PureWindowsPath(path)
    if windows.drive:
        if not windows.drive.endswith(":"):
            raise SandboxError("Docker sandbox does not support UNC paths; use a local drive or WSL")
        return "/host/" + windows.drive[0].lower() + "/" + "/".join(windows.parts[1:])
    return Path(path).as_posix()


def _mount(source: str, target: str, *, readonly: bool) -> list[str]:
    if any(c in source or c in target for c in (",", "\n", "\r")):
        raise SandboxError("Docker sandbox mount paths cannot contain commas or newlines")
    return ["--mount", f"type=bind,src={source},dst={target}" + (",readonly" if readonly else "")]


def container_options(name, policy):
    workspace = str(Path(policy.workspace).resolve(strict=True))
    if not Path(workspace).is_dir():
        raise SandboxError("Docker sandbox workspace must be a directory")
    uid = (os.getuid() or 10001) if hasattr(os, "getuid") else 10001
    gid = (os.getgid() or 10001) if hasattr(os, "getgid") else 10001
    options = [
        "--name", name, "--pull", "never", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", f"{uid}:{gid}", "--cpus", "1", "--memory", "1g",
        "--memory-swap", "1g", "--pids-limit", "64", "--ulimit", "nofile=128:128",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
        "--workdir", container_path(workspace),
        "--env", "HOME=/tmp", "--env", "TMPDIR=/tmp", "--env", "LANG=C.UTF-8",
        "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PYTHONIOENCODING=utf-8",
        "--env", "MPLBACKEND=Agg",
        *_mount(workspace, container_path(workspace), readonly=False),
    ]
    for root in dict.fromkeys(policy.read_roots):
        source = str(Path(root).resolve(strict=True))
        # A read-only mount must not cover the writable workspace.
        if Path(workspace).is_relative_to(source):
            raise SandboxError("Docker sandbox read root overlaps the workspace")
        options += _mount(source, container_path(source), readonly=True)
    # Windows uses a virtual data/ alias instead of privileged directory symlinks.
    if os.name == "nt" and policy.read_roots:
        source = str(Path(policy.read_roots[0]).resolve(strict=True))
        options += _mount(source, container_path(workspace) + "/data", readonly=True)
    return options


async def _capture(argv):
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )

    async def read(stream):
        head, tail, total = bytearray(), bytearray(), 0
        half = MAX_STREAM_BYTES // 2
        while chunk := await stream.read(8192):
            total += len(chunk)
            missing = half - len(head)
            head.extend(chunk[:missing])
            tail.extend(chunk[missing:])
            if len(tail) > half:
                del tail[:-half]
        marker = b"\n... [sandbox output truncated] ...\n" if total > MAX_STREAM_BYTES else b""
        return (head + marker + tail).decode("utf-8", errors="replace")

    readers = [asyncio.create_task(read(proc.stdout)), asyncio.create_task(read(proc.stderr))]
    try:
        stdout, stderr = await asyncio.gather(*readers)
        await proc.wait()
        return proc.returncode, stdout, stderr
    finally:
        if proc.returncode is None:
            proc.kill()
        for task in readers:
            task.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        await proc.wait()


async def run_docker(policy, command: str, timeout: float) -> dict:
    docker = shutil.which("docker")
    if not docker:
        raise SandboxError("Docker CLI unavailable; install Docker Desktop / enable WSL integration; no fallback")
    options_name = "retail-bash-" + uuid.uuid4().hex
    options = container_options(options_name, policy)
    # Translate known Windows roots only; quoted relative commands stay intact.
    for root in sorted((policy.workspace, *policy.read_roots), key=len, reverse=True):
        target = container_path(root)
        if target != root:
            command = command.replace(root, target).replace(root.replace("\\", "/"), target)
    image = os.environ.get("SKILL_SANDBOX_IMAGE", settings.skill_sandbox_image)
    cleanup_needed = False
    try:
        async with asyncio.timeout(timeout):
            code, image_id, _ = await _capture([docker, "image", "inspect", "--format", "{{.Id}}", image])
            if code or not image_id.strip().startswith("sha256:"):
                raise SandboxError("Docker image or daemon unavailable; build the configured Bash image; no fallback")
            cleanup_needed = True
            code, _, _ = await _capture([
                docker, "create", *options, image_id.strip(), "/bin/bash", "-o", "pipefail", "-c", command,
            ])
            if code:
                raise SandboxError("Docker sandbox container creation failed; no fallback")
            code, stdout, stderr = await _capture([docker, "start", "--attach", options_name])
            # Inspect the command's exit status separately from the attach client.
            inspect_code, exit_code, _ = await _capture([
                docker, "inspect", "--format", "{{.State.ExitCode}}", options_name,
            ])
            if inspect_code or not exit_code.strip().isdigit() or (code and exit_code.strip() == "0"):
                raise SandboxError("Docker sandbox result unavailable; no fallback")
            return {"exit_code": int(exit_code.strip()), "stdout": stdout, "stderr": stderr}
    except TimeoutError:
        raise
    except OSError:
        raise SandboxError("Docker sandbox process unavailable; no fallback") from None
    finally:
        if cleanup_needed:
            async def cleanup():
                try:
                    async with asyncio.timeout(15):
                        code, _, _ = await _capture([docker, "rm", "--force", options_name])
                    if code:
                        raise SandboxError("Docker cleanup failed; container may remain: " + options_name)
                except (OSError, TimeoutError):
                    raise SandboxError("Docker cleanup unavailable; container may remain: " + options_name) from None
            task = asyncio.create_task(cleanup())
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise
