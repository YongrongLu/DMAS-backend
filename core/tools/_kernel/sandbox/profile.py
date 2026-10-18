"""macOS Seatbelt profile for an agent's bash commands

Provides:
- seatbelt_profile:     a profile for sandbox-exec built from an agent's AccessPolicy

Key constraints:
- no network: data can never be sent anywhere from a command
- writes only to the agent's workspace and the temp directory
- reads are global (interpreters and libraries live all over the disk)
  except the protected project folders (data/, workspaces/, logs, .env) and
  credentials in the home directory; the agent's own workspace and data
  folder are re-allowed afterwards (the last matching rule wins)
"""

import os
import json


def _subpaths(paths) -> str:
    return " ".join(f'(subpath {json.dumps(p, ensure_ascii=False)})' for p in paths)


def seatbelt_profile(workspace: str, read_roots, protected, sensitive_home, writable_tmp: str) -> str:
    """Return the Seatbelt profile text for one agent."""
    home = os.path.expanduser("~")
    denied = [*protected, *(os.path.join(home, p) for p in sensitive_home)]
    allowed = [workspace, *read_roots]
    return f"""(version 1)
(deny default)
(allow process-exec* process-fork sysctl-read mach-lookup file-map-executable)
(allow signal (target self))
(allow file-read*)
(deny file-read* {_subpaths(denied)})
(allow file-read* {_subpaths(allowed)})
(allow file-write* {_subpaths([workspace, os.path.realpath(writable_tmp)])} (literal "/dev/null"))
(deny network*)
"""
