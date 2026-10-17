"""shell_executor -- runs skill scripts, and nothing else, on a department device

The command looks like a shell command so the agent can copy the usage line
of a SKILL.md, but it never reaches a shell:

    python skills/<skill>/scripts/<script>.py [args...]

Provides:
- shell_executor:       validate one command, run the skill script, gate its output

Key constraints:
- always returns a JSON string (status ok / error / denied); never raises
- allow-list, checked in order, every violation is "denied" and audited:
  no shell operators; interpreter is python; the script resolves inside
  skills/<skill>/scripts/; the skill is enabled for this department
- a command that touches a .csv or the data file itself gets the PRD §9
  denial message: raw data cannot be exported from this device
- the script runs with an empty environment except PATH, PYTHONPATH and the
  department / data path variables: no API keys reach it, and the model can
  neither see nor choose the data path
- on macOS the run is wrapped in the air-gapped Seatbelt profile (no network)
- the result passes policy.check_output before the model sees it: too many
  rows or a restricted identifier in any string turns it into "denied"
- results over SKILL_OUTPUT_MAX_CHARS are refused as "error" rather than
  truncated, because truncated JSON would mislead the model
"""

import asyncio
import json
import os
import shlex
import shutil
import signal
import sys
import tempfile
import time

from core.data import output, policy
from core.data.audit import record_denial
from core.data.constants import ENV_DATA_PATH, ENV_DEPARTMENT
from core.data.loader import load_restricted_values
from core.departments import get_department
from core.departments.base import DepartmentSpec
from core.tools._kernel._skills import skills_for
from core.tools._kernel.constants import (
    ALLOWED_INTERPRETERS,
    PROJECT_ROOT,
    SANDBOX_ENABLED,
    SHELL_DEFAULT_TIMEOUT,
    SHELL_MAX_COMMAND_CHARS,
    SHELL_MAX_TIMEOUT,
    SHELL_OPERATOR_CHARS,
    SHELL_STDERR_TAIL_CHARS,
    SKILL_OUTPUT_MAX_CHARS,
    SKILL_SCRIPTS_DIR,
    SKILLS_DIR,
)
from core.tools._kernel.sandbox.profile import air_gapped_profile
from utils.logging import get_logger

logger = get_logger(__name__)

TOOL_NAME = "shell_executor"
USAGE = "python skills/<skill>/scripts/<script>.py [args]"


def _error(message: str) -> str:
    """A malformed call: status error."""
    return json.dumps({"status": "error", "tool_name": TOOL_NAME, "message": message}, ensure_ascii=False)


def _deny(spec: DepartmentSpec, reason: str, command: str, *, raw_access: bool) -> str:
    """A refused call: status denied, audited on the device terminal."""
    record_denial(spec.name, TOOL_NAME, reason, command)
    result = output.denied(TOOL_NAME, spec, reason)
    if not raw_access:
        result["message"] = f"Only skill scripts can run on this device: {USAGE}"
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def _split(command: str) -> list[str]:
    """Split like a POSIX shell; unquoted operators become their own tokens."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=SHELL_OPERATOR_CHARS)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _touches_data(tokens: list[str], data_path: str) -> bool:
    """Whether the command names a CSV or the department's data file."""
    data_name = os.path.basename(data_path)
    return any(t.lower().endswith(".csv") or data_name in t for t in tokens)


def _resolve_script(token: str, skills_dir: str, project_root: str) -> tuple[str, str] | None:
    """Resolve the script token to (skill name, absolute path), or None when it is not a skill script."""
    path = os.path.realpath(os.path.join(project_root, token))
    root = os.path.realpath(skills_dir)
    if not path.startswith(root + os.sep) or not path.endswith(".py") or not os.path.isfile(path):
        return None
    parts = os.path.relpath(path, root).split(os.sep)
    if len(parts) != 3 or parts[1] != SKILL_SCRIPTS_DIR:
        return None
    return parts[0], path


def _skill_of(token: str, skills_dir: str, project_root: str) -> str | None:
    """The skill folder a path points into, even when the file itself does not exist."""
    path = os.path.realpath(os.path.join(project_root, token))
    root = os.path.realpath(skills_dir)
    if not path.startswith(root + os.sep):
        return None
    return os.path.relpath(path, root).split(os.sep)[0]


def _environment(spec: DepartmentSpec, data_path: str, project_root: str) -> dict[str, str]:
    """The only variables the script sees."""
    tmp = tempfile.gettempdir()
    return {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": project_root,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "HOME": tmp,
        "TMPDIR": tmp,
        ENV_DEPARTMENT: spec.name,
        ENV_DATA_PATH: os.path.realpath(data_path),
    }


async def _run(argv: list[str], env: dict, cwd: str, timeout: float, sandbox: bool) -> dict:
    """Run the script, optionally inside the air-gapped Seatbelt profile; kill its group on timeout."""
    profile_path = None
    if sandbox and sys.platform == "darwin" and shutil.which("sandbox-exec"):
        with tempfile.NamedTemporaryFile("w", suffix=".sb", delete=False) as f:
            f.write(air_gapped_profile(tempfile.gettempdir()))
            profile_path = f.name
        argv = ["sandbox-exec", "-f", profile_path, *argv]

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=cwd, env=env, start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()
            return {"timeout": True, "exit_code": None, "stdout": "", "stderr": ""}
        return {
            "timeout": False,
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
    finally:
        if profile_path:
            try:
                os.unlink(profile_path)
            except OSError:
                pass


async def shell_executor(
    command: str,
    department: str,
    data_path: str,
    timeout: float = SHELL_DEFAULT_TIMEOUT,
    *,
    skills_dir: str = SKILLS_DIR,
    project_root: str = PROJECT_ROOT,
    sandbox: bool = SANDBOX_ENABLED,
) -> str:
    """Run one skill script for a department and return its gated result.

    Args:
        command:        e.g. "python skills/time-trend/scripts/trend.py --metric revenue".
        department:     the department this agent belongs to.
        data_path:      the department view; injected into the script's environment.
        timeout:        seconds before the run is killed.
        skills_dir:     where the skills live (tests point it elsewhere).
        project_root:   cwd and PYTHONPATH of the run.
        sandbox:        allow the Seatbelt wrapper on macOS.

    Returns:
        the skill's JSON result, or an error / denied JSON.
    """
    try:
        spec = get_department(department)
    except KeyError as exc:
        return _error(str(exc))
    if not isinstance(command, str) or not command.strip():
        return _error("command must be a non-empty string")
    if len(command) > SHELL_MAX_COMMAND_CHARS:
        return _error(f"command too long ({len(command)} chars); max {SHELL_MAX_COMMAND_CHARS}")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= SHELL_MAX_TIMEOUT:
        return _error(f"timeout must be a number in (0, {SHELL_MAX_TIMEOUT}]")
    if not os.path.isfile(data_path):
        return _error(f"data file for {department} is not available on this device")

    try:
        tokens = _split(command)
    except ValueError as exc:
        return _error(f"cannot parse command: {exc}")

    raw_access = _touches_data(tokens, data_path)
    if any(t and set(t) <= set(SHELL_OPERATOR_CHARS) for t in tokens):
        return _deny(spec, "shell operators (pipes, redirects, ;, &&) are not supported; run one skill script per call",
                     command, raw_access=raw_access)
    if tokens[0] not in ALLOWED_INTERPRETERS or len(tokens) < 2:
        return _deny(spec, f"only skill scripts can run on this device, not {tokens[0]!r}", command, raw_access=raw_access)

    resolved = _resolve_script(tokens[1], skills_dir, project_root)
    if resolved is None:
        # 写错了某个可用 skill 的脚本名：是笔误，不是越权，返回正确路径让模型改正
        guess = _skill_of(tokens[1], skills_dir, project_root)
        available = {s.name: s for s in skills_for(spec.name, skills_dir, project_root)}
        if guess in available and not raw_access:
            return _error(f"{tokens[1]!r} does not exist; {guess} runs: "
                          + ", ".join(f"python {p}" for p in available[guess].scripts))
        return _deny(spec, f"{tokens[1]!r} is not a skill script", command, raw_access=raw_access)
    skill, script_path = resolved
    if skill not in {s.name for s in skills_for(spec.name, skills_dir, project_root)}:
        return _deny(spec, f"skill {skill!r} is not available to the {spec.name} department", command, raw_access=False)

    t_start = time.time()
    run = await _run([sys.executable, script_path, *tokens[2:]], _environment(spec, data_path, project_root),
                     project_root, timeout, sandbox)
    elapsed = round(time.time() - t_start, 2)

    if run["timeout"]:
        logger.warning("skill_timeout", department=spec.name, skill=skill, timeout=timeout)
        return _error(f"{skill} did not finish within {timeout}s; narrow the query")
    try:
        result = json.loads(run["stdout"].strip())
        if not isinstance(result, dict) or "status" not in result:
            raise ValueError("not a skill result")
    except ValueError:
        return _error(f"{skill} failed (exit code {run['exit_code']}): {run['stderr'][-SHELL_STDERR_TAIL_CHARS:].strip()}")

    if result["status"] == "denied":
        record_denial(spec.name, skill, (result.get("notes") or [result.get("message", "")])[0], command)
    else:
        violation = policy.check_output(result, load_restricted_values(spec, data_path))
        if violation:
            record_denial(spec.name, f"{TOOL_NAME} output gate", violation, command)
            result = output.denied(skill, spec, f"output blocked: {violation}")

    text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if len(text) > SKILL_OUTPUT_MAX_CHARS:
        return _error(f"{skill} returned {len(text)} chars, more than {SKILL_OUTPUT_MAX_CHARS}; "
                      f"ask for fewer rows or groups")

    logger.debug("skill_run", department=spec.name, skill=skill, status=result["status"], elapsed=elapsed)
    return text
