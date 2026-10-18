"""bash -- run a shell command in the agent's workspace, sandboxed

Provides:
- bash:     run one command and return its exit code and (capped) output

Key constraints:
- cwd is the agent's workspace; Python and pandas come from the macOS venv
  or the configured Docker image on Windows/WSL/Linux
- the environment is rebuilt from scratch: no API keys or other secrets
  reach the command
- on macOS the command runs under a Seatbelt profile from the agent's
  AccessPolicy: no network, writes only in the workspace, other departments'
  data, private/, .env and credentials unreadable; a blocked access is
  audited with 🔒
- the whole process group is killed on timeout
- never raises; returns text for the model
"""

import asyncio
import os
import shutil
import signal
import sys
import tempfile

from core.middlewares.audit import record_denial
from core.tools._kernel._access import AccessPolicy
from core.tools._kernel.constants import (
    BASH_DEFAULT_TIMEOUT,
    BASH_MAX_OUTPUT_CHARS,
    BASH_MAX_TIMEOUT,
    PROJECT_ROOT,
    SANDBOX_ENABLED,
    SENSITIVE_HOME_PATHS,
)
from core.tools._kernel.sandbox.profile import seatbelt_profile
from core.tools._kernel.sandbox.docker_runner import SandboxError, run_docker
from utils.runtime import portable_relative_path, selected_sandbox_backend


def _environment(policy: AccessPolicy) -> dict[str, str]:
    """A clean environment: the project venv first on PATH, nothing secret."""
    tmp = tempfile.gettempdir()
    venv_bin = os.path.dirname(sys.executable)
    return {
        "PATH": f"{venv_bin}:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
        "HOME": tmp,
        "TMPDIR": tmp,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "MPLBACKEND": "Agg",
        "LANG": "en_US.UTF-8",
    }


def _cap(text: str, limit: int) -> str:
    """Keep the head and the tail of a long output."""
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n... [{len(text) - limit:,} chars cut] ...\n{text[-half:]}"


async def bash(policy: AccessPolicy, command: str, timeout: float = BASH_DEFAULT_TIMEOUT,
               sandbox: bool = SANDBOX_ENABLED) -> str:
    """Run one bash command in the workspace and return its result as text."""
    if not str(command).strip():
        return "Error: empty command"
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= BASH_MAX_TIMEOUT:
        return f"Error: timeout must be a number in (0, {BASH_MAX_TIMEOUT}]"

    backend = selected_sandbox_backend()
    if backend == "docker":
        try:
            run = await run_docker(policy, command, timeout)
        except TimeoutError:
            return f"Error: command timed out after {timeout:.0f}s and was killed; make it faster or narrower"
        except (SandboxError, OSError, ValueError) as exc:
            return f"Error: {exc}" if isinstance(exc, SandboxError) else "Error: Docker sandbox paths unavailable; no fallback"
        return _format_result(run["exit_code"], run["stdout"], run["stderr"], policy, command)
    if backend != "seatbelt" or sys.platform != "darwin" or not sandbox or not shutil.which("sandbox-exec"):
        return "Error: sandbox unavailable or unsupported backend; no fallback"

    argv = ["/bin/bash", "-o", "pipefail", "-c", command]
    profile_path = None
    if sandbox and sys.platform == "darwin" and shutil.which("sandbox-exec"):
        with tempfile.NamedTemporaryFile("w", suffix=".sb", delete=False) as f:
            f.write(seatbelt_profile(policy.workspace, policy.read_roots, policy.protected,
                                     SENSITIVE_HOME_PATHS, tempfile.gettempdir()))
            profile_path = f.name
        argv = ["sandbox-exec", "-f", profile_path, *argv]

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=policy.workspace, env=_environment(policy), start_new_session=True,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except (TimeoutError, asyncio.CancelledError) as exc:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            return f"Error: command timed out after {timeout:.0f}s and was killed; make it faster or narrower"
    except OSError:
        return "Error: Seatbelt sandbox process unavailable; no fallback"
    finally:
        if profile_path:
            os.unlink(profile_path)

    stdout = out.decode("utf-8", errors="replace")
    stderr = err.decode("utf-8", errors="replace")
    return _format_result(proc.returncode, stdout, stderr, policy, command)


def _format_result(exit_code: int, stdout: str, stderr: str, policy: AccessPolicy, command: str) -> str:
    """Keep xyz-1's tool result format for the model and streaming callbacks."""
    # 沙箱拦下的读取：碰到了受保护的项目目录（别的部门、private/、.env ...）就记一笔 🔒
    if "Operation not permitted" in stderr and any(portable_relative_path(p, PROJECT_ROOT) in stderr
                                                    or p in stderr for p in policy.protected):
        record_denial(policy.owner, "bash sandbox", "a command tried to read data outside this department's authorization",
                      command)

    parts = [f"exit code {exit_code}"]
    if stdout.strip():
        parts.append("stdout:\n" + stdout.rstrip())
    if stderr.strip():
        parts.append("stderr:\n" + stderr.rstrip())
    return _cap("\n".join(parts), BASH_MAX_OUTPUT_CHARS)
