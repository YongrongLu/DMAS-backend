"""Sandbox selection from trusted local configuration."""
import os
import sys


def portable_relative_path(path: str, start: str) -> str:
    """Display a shell-friendly path, including data on another Windows drive."""
    try:
        path = os.path.relpath(path, start)
    except ValueError:
        # Windows cannot express a relative path between drive letters.
        pass
    return path.replace(os.sep, "/")


def default_sandbox_backend() -> str:
    return "seatbelt" if sys.platform == "darwin" else "docker"


def selected_sandbox_backend() -> str:
    from utils.settings import settings
    return os.environ.get("SKILL_SANDBOX_BACKEND", settings.skill_sandbox_backend)
