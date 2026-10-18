"""Cross-platform regressions against xyz-1's actual Bash and approval flow."""
import asyncio
import dataclasses
import json
import ntpath
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from core.agents.worker import graph as worker
from core.departments import DepartmentCard
from core.tools._kernel import _bash, _access, _files
from core.tools._kernel._access import AccessDenied, AccessPolicy
from core.tools._kernel.sandbox import docker_runner as docker
from utils import runtime


@pytest.fixture
def policy(tmp_path):
    workspace = tmp_path / "项目 with spaces" / "workspaces" / "product"
    shared = tmp_path / "项目 with spaces" / "data" / "product" / "shared"
    private = shared.parent / "private"
    for folder in (workspace, shared, private):
        folder.mkdir(parents=True)
        folder.chmod(0o777 if folder == workspace else 0o755)
    (shared / "data.csv").write_text("category,value\nGarden,42\nGarden,8\n", encoding="utf-8")
    (private / "costs.csv").write_text("TEST_PRIVATE,123\n", encoding="utf-8")
    if os.name != "nt":
        (workspace / "data").symlink_to(shared, target_is_directory=True)
    return AccessPolicy("product", str(workspace), (str(shared),), (str(shared.parent),))


@pytest.mark.parametrize("platform,expected", [("darwin", "seatbelt"), ("win32", "docker"), ("linux", "docker")])
def test_platform_default(monkeypatch, platform, expected):
    monkeypatch.setattr(runtime.sys, "platform", platform)
    assert runtime.default_sandbox_backend() == expected


def test_windows_container_paths():
    assert docker.container_path(r"D:\项目 with spaces\workspaces\product") == "/host/d/项目 with spaces/workspaces/product"
    with pytest.raises(docker.SandboxError):
        docker.container_path(r"\\server\share\workspace")


def test_cross_drive_display_does_not_bypass_access_policy(policy, monkeypatch):
    def different_drives(*args):
        raise ValueError("path and start are on different Windows drives")
    monkeypatch.setattr(runtime.os.path, "relpath", different_drives)
    assert runtime.portable_relative_path("D:/data/private", "C:/workspace") == "D:/data/private"
    with pytest.raises(AccessDenied, match="outside this department"):
        policy.check_read(str(Path(policy.read_roots[0]).parent / "private/costs.csv"))


def test_windows_alias_and_cross_drive_policy_on_every_host(monkeypatch):
    # Exercise native Windows path rules even when CI runs on macOS/Linux.
    monkeypatch.setattr(_access, "os", SimpleNamespace(name="nt", path=ntpath, sep="\\"))
    monkeypatch.setattr(_access, "record_denial", lambda *args: None)
    workspace = r"C:\Repo\workspaces\product"
    shared = r"D:\datasets\product\shared"
    active = AccessPolicy("product", workspace, (shared,), (r"D:\datasets",))
    for path in ("data/data.csv", "./data/data.csv", r"DATA\data.csv",
                 r"c:\repo\WORKSPACES\product\data\data.csv"):
        assert ntpath.normcase(active.check_read(path)) == ntpath.normcase(shared + r"\data.csv")
        with pytest.raises(AccessDenied):
            active.check_write(path)
    with pytest.raises(AccessDenied):
        active.check_read(r"data\..\private\costs.csv")
    with pytest.raises(AccessDenied):
        active.check_read(r"D:\datasets\sales\shared\data.csv")


def test_mounts_only_active_authorization(policy):
    options = docker.container_options("test", policy)
    assert "--network" in options and "none" in options and "--read-only" in options
    assert policy.read_roots[0] in " ".join(options)
    private = str(Path(policy.read_roots[0]).parent / "private")
    assert private not in " ".join(options)
    granted = dataclasses.replace(policy, read_roots=(*policy.read_roots, private))
    assert f"src={private},dst={docker.container_path(private)},readonly" in " ".join(docker.container_options("test", granted))


def test_windows_virtual_data_alias(policy):
    if os.name != "nt":
        pytest.skip("Native Windows alias")
    assert _files.view_file(policy, "data/data.csv").startswith("data/data.csv lines")
    assert policy.check_read("./data/data.csv") == policy.check_read("data/data.csv")
    assert policy.check_read(str(Path(policy.workspace) / "data/data.csv")) == policy.check_read("data/data.csv")
    assert "data/data.csv" in _files.glob_tool(policy, "**/*", "data")
    with pytest.raises(AccessDenied):
        policy.check_write("data/data.csv")
    with pytest.raises(AccessDenied):
        policy.check_read("data/../private/costs.csv")


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["none", "seatbelt", "invalid"])
async def test_no_unisolated_fallback(policy, monkeypatch, backend):
    monkeypatch.setenv("SKILL_SANDBOX_BACKEND", backend)
    monkeypatch.setattr(_bash.sys, "platform", "win32")
    assert "no fallback" in await _bash.bash(policy, "echo must-not-run")


@pytest.mark.asyncio
async def test_missing_docker_returns_safe_error(policy, monkeypatch):
    monkeypatch.setenv("SKILL_SANDBOX_BACKEND", "docker")
    monkeypatch.setattr(docker.shutil, "which", lambda _: None)
    assert "no fallback" in await _bash.bash(policy, "echo must-not-run")


@pytest.mark.asyncio
async def test_macos_keeps_seatbelt_and_output_contract(policy, monkeypatch):
    monkeypatch.setenv("SKILL_SANDBOX_BACKEND", "seatbelt")
    monkeypatch.setattr(_bash.sys, "platform", "darwin")
    monkeypatch.setattr(_bash.shutil, "which", lambda _: "/usr/bin/sandbox-exec")
    calls = []
    class Process:
        returncode = 7
        async def communicate(self):
            return b"result\n", b"diagnostic\n"
    async def spawn(*argv, **kwargs):
        calls.append(argv)
        profile = Path(argv[2]).read_text()
        assert "(deny network*)" in profile
        return Process()
    monkeypatch.setattr(_bash.asyncio, "create_subprocess_exec", spawn)
    assert await _bash.bash(policy, "python analysis.py") == "exit code 7\nstdout:\nresult\nstderr:\ndiagnostic"
    assert calls[0][0] == "sandbox-exec"


@pytest.mark.asyncio
async def test_capture_drains_but_bounds_large_output():
    code, out, err = await docker._capture([sys.executable, "-c", "import sys; print('x'*200000); sys.stderr.write('y'*200000)"])
    assert code == 0
    assert len(out) < 66000 and len(err) < 66000
    assert "truncated" in out and "truncated" in err


@pytest.mark.asyncio
async def test_failed_create_keeps_original_error_when_container_is_absent(policy, monkeypatch):
    monkeypatch.setattr(docker.shutil, "which", lambda _: "/test/docker")
    calls = []

    async def capture(argv):
        calls.append(argv)
        if argv[1] == "image":
            return 0, "sha256:" + "a" * 64, ""
        if argv[1] == "create":
            return 125, "", "DO_NOT_LEAK_DOCKER_DIAGNOSTIC"
        if argv[1] == "rm":
            return 1, "", "container does not exist"
        assert argv[1] == "ps"
        return 0, "", ""

    monkeypatch.setattr(docker, "_capture", capture)
    with pytest.raises(docker.SandboxError, match="container creation failed"):
        await docker.run_docker(policy, "echo test", 5)
    assert [argv[1] for argv in calls] == ["image", "create", "rm", "ps"]


@pytest.mark.asyncio
@pytest.mark.parametrize("listing_fails", [False, True])
async def test_cleanup_failure_is_reported_if_presence_cannot_be_ruled_out(policy, monkeypatch, listing_fails):
    monkeypatch.setattr(docker.shutil, "which", lambda _: "/test/docker")

    async def capture(argv):
        if argv[1] == "image":
            return 0, "sha256:" + "a" * 64, ""
        if argv[1] in ("create", "rm"):
            return 1, "", "DO_NOT_LEAK_DOCKER_DIAGNOSTIC"
        assert argv[1] == "ps"
        name = argv[argv.index("--filter") + 1].removeprefix("name=")
        return (1, "", "daemon unavailable") if listing_fails else (0, name + "\n", "")

    monkeypatch.setattr(docker, "_capture", capture)
    with pytest.raises(docker.SandboxError, match="cleanup failed; container may remain"):
        await docker.run_docker(policy, "echo test", 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_container_cleanup_on_timeout_and_cancellation(policy, monkeypatch, cancel):
    monkeypatch.setattr(docker.shutil, "which", lambda _: "/test/docker")
    started = asyncio.Event()
    removed = []

    async def capture(argv):
        if argv[1] == "image":
            return 0, "sha256:" + "a" * 64, ""
        if argv[1] == "create":
            return 0, "container-id", ""
        if argv[1] == "start":
            started.set()
            await asyncio.Event().wait()
        assert argv[1] == "rm"
        removed.append(argv[-1])
        return 0, "", ""

    monkeypatch.setattr(docker, "_capture", capture)
    job = asyncio.create_task(docker.run_docker(policy, "sleep 30", 5 if cancel else .05))
    await asyncio.wait_for(started.wait(), timeout=1)
    if cancel:
        job.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
        await job
    assert len(removed) == 1 and removed[0].startswith("retail-bash-")


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, *args, **kwargs):
        return self


@pytest.mark.asyncio
async def test_docker_missing_private_triggers_existing_owner_gate(policy, monkeypatch):
    card = DepartmentCard("product", "Product", "Product analysis", str(Path(policy.read_roots[0]).parent))
    relative = os.path.relpath(card.private_dir, policy.workspace).replace(os.sep, "/")
    calls = []
    async def fake_bash(active, command, timeout=60):
        calls.append(active)
        if card.private_dir not in active.read_roots:
            return f"exit code 1\nstderr:\n{relative}/costs.csv: No such file or directory"
        return "exit code 0\nstdout:\nAggregate cost: 123"
    model = ScriptedModel(responses=[
        AIMessage(content="", tool_calls=[{"name": "load_skill", "args": {"name": "tabular-analysis"}, "id": "skill"}]),
        AIMessage(content="", tool_calls=[{"name": "bash", "args": {"command": "cat '" + relative + "/costs.csv'"}, "id": "blocked"}]),
        AIMessage(content="", tool_calls=[{"name": "bash", "args": {"command": "cat '" + relative + "/costs.csv'"}, "id": "retry"}]),
        AIMessage(content="Aggregate cost is 123."),
    ])
    monkeypatch.setattr(worker, "chat_model", lambda: model)
    monkeypatch.setattr(_bash, "bash", fake_bash)
    approvals = []
    async def approve(request):
        approvals.append(request["kind"])
        return True
    graph = worker.build_department_graph(card, policy)
    result = await worker.run_department_task(graph, card, {"task_id": "sandbox-test", "question": "Aggregate cost?"}, approve)
    assert result["status"] == "success"
    assert approvals == ["task", "access", "deliver"]
    assert card.private_dir not in calls[0].read_roots
    assert card.private_dir in calls[1].read_roots
    assert card.private_dir not in policy.read_roots


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "darwin" or os.environ.get("RUN_SEATBELT_TESTS") != "1",
                    reason="Set RUN_SEATBELT_TESTS=1 on macOS for native Seatbelt acceptance")
async def test_real_macos_seatbelt_analysis_and_isolation(policy, tmp_path, monkeypatch):
    monkeypatch.setenv("SKILL_SANDBOX_BACKEND", "seatbelt")
    monkeypatch.setenv("SANDBOX_TEST_HOST_SECRET", "MUST_NOT_ENTER_COMMAND")
    scratch = tmp_path / "sandbox-tmp"
    scratch.mkdir()
    # Keep sandbox-writable temporary files separate from fixture data.
    monkeypatch.setattr(_bash.tempfile, "gettempdir", lambda: str(scratch))
    private = str(Path(policy.read_roots[0]).parent / "private/costs.csv")
    script = f"""import os, socket
import pandas as pd
assert 'SANDBOX_TEST_HOST_SECRET' not in os.environ
assert pd.read_csv('data/data.csv').value.sum() == 50
try:
    open({private!r}).read()
except PermissionError:
    pass
else:
    raise AssertionError('private data was readable')
try:
    open('data/data.csv', 'a').write('must-not-write')
except PermissionError:
    pass
else:
    raise AssertionError('shared data was writable')
try:
    with socket.socket() as connection:
        connection.bind(('127.0.0.1', 0))
except PermissionError:
    pass
else:
    raise AssertionError('network was available')
open('report.txt', 'w').write('total=50')
print('native Seatbelt analysis and isolation passed')
"""
    _files.write_file(policy, "analysis.py", script)
    result = await _bash.bash(policy, "python analysis.py")
    assert result.startswith("exit code 0"), result
    assert "native Seatbelt analysis and isolation passed" in result
    assert "total=50" in _files.view_file(policy, "report.txt")


@pytest.fixture
def live_docker(monkeypatch):
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Set RUN_DOCKER_TESTS=1 after building retail-bash:xyz-1")
    monkeypatch.setenv("SKILL_SANDBOX_BACKEND", "docker")
    assert shutil.which("docker"), "Docker CLI is required for requested acceptance tests"


@pytest.mark.asyncio
async def test_real_bash_pandas_data_and_workspace(policy, live_docker):
    _files.write_file(policy, "analysis.py", "import pandas as pd\ndf = pd.read_csv('data/data.csv')\nprint(df.value.sum())\nopen('report.txt', 'w').write('total=50')\n")
    result = await _bash.bash(policy, "python analysis.py")
    assert "exit code 0" in result and "50" in result, result
    assert "total=50" in _files.view_file(policy, "report.txt")
    result = await _bash.bash(policy, "echo must-not-write >> data/data.csv")
    assert not result.startswith("exit code 0"), result
    assert "must-not-write" not in Path(policy.read_roots[0], "data.csv").read_text()


@pytest.mark.asyncio
async def test_real_grant_and_revoke_private_mount(policy, live_docker):
    private = str(Path(policy.read_roots[0]).parent / "private")
    rel = os.path.relpath(private, policy.workspace).replace(os.sep, "/")
    command = f"cat '{rel}/costs.csv'"
    assert "TEST_PRIVATE" not in await _bash.bash(policy, command)
    granted = dataclasses.replace(policy, read_roots=(*policy.read_roots, private))
    assert "TEST_PRIVATE" in await _bash.bash(granted, command)
    assert "TEST_PRIVATE" not in await _bash.bash(policy, command)


@pytest.mark.asyncio
async def test_real_network_env_and_exit_code(policy, live_docker, monkeypatch):
    monkeypatch.setenv("SANDBOX_TEST_HOST_SECRET", "MUST_NOT_ENTER_CONTAINER")
    _files.write_file(policy, "isolation.py", "import os, socket\nassert 'SANDBOX_TEST_HOST_SECRET' not in os.environ\ns = socket.socket()\ns.settimeout(.2)\nassert s.connect_ex(('1.1.1.1', 443)) != 0\nprint('isolated')\n")
    assert "isolated" in await _bash.bash(policy, "python isolation.py")
    assert (await _bash.bash(policy, "echo diagnostic >&2; exit 7")).startswith("exit code 7\nstderr:\ndiagnostic")


@pytest.mark.asyncio
async def test_real_timeout_and_cancellation_cleanup(policy, live_docker, monkeypatch):
    # Observe only this test's containers, so concurrent OS acceptance runs do not interfere.
    created = set()
    capture = docker._capture
    async def track(argv):
        if argv[1] == "create":
            created.add(argv[argv.index("--name") + 1])
        return await capture(argv)
    monkeypatch.setattr(docker, "_capture", track)
    def names():
        listed = subprocess.check_output(["docker", "ps", "-a", "--filter", "name=retail-bash-", "--format", "{{.Names}}"], text=True).splitlines()
        return created.intersection(listed)
    assert "timed out" in await _bash.bash(policy, "sleep 30", timeout=2)
    assert not names()
    job = asyncio.create_task(_bash.bash(policy, "sleep 30"))
    for _ in range(100):
        await asyncio.sleep(.1)
        if names():
            break
    assert names()
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    assert not names()


@pytest.mark.asyncio
async def test_real_missing_image_has_no_fallback(policy, live_docker, monkeypatch):
    monkeypatch.setenv("SKILL_SANDBOX_IMAGE", "retail-bash:deliberately-missing")
    result = await _bash.bash(policy, "echo must-not-run")
    assert result.startswith("Error:") and "no fallback" in result
