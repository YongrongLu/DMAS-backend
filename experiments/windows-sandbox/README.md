# Windows sandbox for xyz-1

This ports the Docker isolation approach from `codex/cross-platform-compat`
onto **xyz-1's Bash tool and AccessPolicy**. It does not restore the retired
`shell_executor`, `core/data`, old skill scripts, or old department graph.
The existing APIs, streaming events, skill-first rule, and task/access/delivery
approvals remain in place. No model configuration changes are required.

## Backends

| Host | Default | Prerequisites |
| --- | --- | --- |
| macOS | Seatbelt | Existing Python environment and `sandbox-exec` |
| Windows | Docker | Python 3.11+, Docker Desktop using Linux containers |
| WSL2 / Linux | Docker | Python 3.11+, Docker CLI and local Linux container daemon |

Leave `SKILL_SANDBOX_BACKEND` unset to select automatically. An explicit value
in `.env` overrides that selection. Missing isolation returns an error; commands
never silently execute on the host. macOS continues using its original Seatbelt
profile and Python environment. Use a local Docker daemon, with WSL integration
enabled when running from WSL; remote daemons cannot mount local workspaces.

## Windows PowerShell setup

Run from the repository root with Python 3.11 or newer (`python --version`).
The machine's default Python may be older; select a suitable installed version.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
docker build -f experiments/windows-sandbox/Dockerfile -t retail-bash:xyz-1 .
.\.venv\Scripts\python.exe -m server.main
```

Department dashboard example (another terminal):

```powershell
.\.venv\Scripts\python.exe -m server.department --department product --port 8101
```

The existing `python -m distributed.agent --department product` command also
works. CLI owner approvals use the existing terminal fallback on Windows;
dashboard approvals continue through the department API.

In WSL, use `.venv/bin/python` and the same Docker build command. A workspace
on the Linux filesystem usually performs better than one under `/mnt/c`.
For macOS setup and the existing API contract, see `../../server/README.md`.

## Files and isolation

Each Bash invocation gets a fresh container: no network, read-only root,
no added capabilities, no new privileges, and CPU/memory/PID limits. Only its
workspace is writable; shared data and task-approved private directories are
mounted read-only. No repository, `.env`, host home, Docker socket, or other
department directory is mounted. The environment does not inherit model keys.
Timeouts and cancellation forcibly remove the command's container.

Scripts still run as `python analysis.py` in the workspace and read `data/...`.
Use forward slashes and relative paths in Bash/scripts on every OS. Native
Windows uses a virtual `data/` alias in file tools and a container data mount,
so creating the department workspace requires no symlink privilege. Relative
paths to private data shown by the existing approval flow continue to work.
Windows drive paths in known workspace/read roots are mapped under `/host/c/`,
`/host/d/`, etc. UNC paths and mount paths containing commas are rejected.

The image contains Python, Bash, pandas, NumPy and openpyxl. Add dependencies
needed for other formats to `requirements.txt` in this directory and rebuild
before running; package installation inside a command has no network access.
An unprivileged Linux host must own its workspace; a root host needs a workspace
writable by container UID 10001. Shared data must be readable by the container.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
$env:RUN_DOCKER_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox_compat.py -q
```

On WSL/Linux: `RUN_DOCKER_TESTS=1 .venv/bin/python -m pytest -q`.
Docker tests are opt-in and fail if requested dependencies are unavailable.
The Windows symlink inventory test skips only when the OS refuses symlink
creation; it still runs on Linux/macOS. Simulated macOS tests verify backend
selection and the existing Seatbelt invocation; they are not a macOS device run.
