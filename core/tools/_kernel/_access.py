"""Access policy of an agent: which paths it may read and write

Every file tool and every bash command of an agent goes through one
AccessPolicy:

- read:     the agent's workspace, and for a department its own shared/ data
            (linked into the workspace as data/)
- write:    the workspace only; the data link resolves outside it, so data
            files can never be modified
- denied:   anything under data/ that is not this department's shared/
            folder (other departments, private/, raw/, processed/), other
            workspaces, logs and .env; a denied read is audited with 🔒

Provides:
- AccessPolicy:         the policy of one agent
- AccessDenied:         raised for a forbidden path; the message is shown to the model
- department_policy:    the policy of a department agent (creates its workspace and data link)
- orchestrator_policy:  the policy of the orchestrator (its workspace only)

Key constraints:
- paths are resolved with realpath before any check, so symlinks and ../
  cannot escape
- relative paths are relative to the workspace
"""

import os
from dataclasses import dataclass

from core.departments import DepartmentCard
from core.middlewares.audit import record_denial
from core.tools._kernel.constants import DATA_LINK, PROJECT_ROOT, WORKSPACES_DIR


class AccessDenied(PermissionError):
    """A path the agent is not allowed to touch."""


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


@dataclass(frozen=True)
class AccessPolicy:
    """Where one agent may read and write.

    Attributes:
        owner:          who the policy belongs to, for audit lines (e.g. "customer").
        workspace:      the agent's working directory; readable and writable.
        read_roots:     extra readable directories (a department's shared/ folder).
        protected:      directories that are denied unless inside a read root.
    """
    owner: str
    workspace: str
    read_roots: tuple[str, ...] = ()
    protected: tuple[str, ...] = ()

    def resolve(self, path: str) -> str:
        """Absolute real path of a path given relative to the workspace."""
        expanded = os.path.expanduser(str(path).strip() or ".")
        return os.path.realpath(expanded if os.path.isabs(expanded) else os.path.join(self.workspace, expanded))

    def check_read(self, path: str) -> str:
        """Resolve a path the agent wants to read.

        Raises:
            AccessDenied: outside the workspace and the read roots.
        """
        real = self.resolve(path)
        if _inside(real, self.workspace) or any(_inside(real, root) for root in self.read_roots):
            return real
        if any(_inside(real, root) for root in self.protected):
            reason = f"read of {os.path.relpath(real, PROJECT_ROOT)} is outside this department's authorized data"
            record_denial(self.owner, "file access", reason, str(path))
            raise AccessDenied(f"Access denied: {reason}.")
        raise AccessDenied(f"{path} is outside your workspace; work inside {self.workspace}")

    def check_write(self, path: str) -> str:
        """Resolve a path the agent wants to write.

        Raises:
            AccessDenied: anywhere outside the workspace, including the data link.
        """
        real = self.resolve(path)
        if _inside(real, self.workspace):
            return real
        if any(_inside(real, root) for root in self.read_roots):
            raise AccessDenied(f"{path} is read-only department data; write your files in the workspace instead")
        raise AccessDenied(f"{path} is outside your workspace; you can only write inside {self.workspace}")


def _protected_roots() -> tuple[str, ...]:
    """Directories no agent may read unless explicitly granted."""
    return tuple(os.path.realpath(os.path.join(PROJECT_ROOT, p)) for p in ("data", "workspaces", "logs", ".env"))


def department_policy(card: DepartmentCard) -> AccessPolicy:
    """The policy of a department agent; creates workspaces/<name>/ with a data/ link to shared/."""
    workspace = os.path.realpath(os.path.join(WORKSPACES_DIR, card.name))
    os.makedirs(workspace, exist_ok=True)
    link = os.path.join(workspace, DATA_LINK)
    shared = os.path.realpath(card.shared_dir)
    if os.path.islink(link) and os.path.realpath(link) != shared:
        os.unlink(link)
    if not os.path.lexists(link):
        os.symlink(shared, link)
    return AccessPolicy(owner=card.name, workspace=workspace, read_roots=(shared,), protected=_protected_roots())


def orchestrator_policy() -> AccessPolicy:
    """The policy of the orchestrator: its own workspace, no department data."""
    workspace = os.path.realpath(os.path.join(WORKSPACES_DIR, "orchestrator"))
    os.makedirs(workspace, exist_ok=True)
    return AccessPolicy(owner="orchestrator", workspace=workspace, protected=_protected_roots())
