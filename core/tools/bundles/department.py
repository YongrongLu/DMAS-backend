"""Tool definitions owned by a department agent.

Lightweight wrappers binding kernel implementations to the @tool decorator.
Each department process (or, in local mode, each department subgraph) gets
its own pair, bound to its department and data file.

Tools provided:
    ├── load_skill                      read a skill's instructions
    └── shell_executor                  run one skill script

Provides:
- build_department_tools:   the two tools bound to one department and its data file

Key constraints:
- load_skill's `name` is an enum of the department's skills, so the model
  can only pick a skill that exists for it
- the data path is captured here and never exposed as a tool argument
"""

from typing import Literal

from langchain_core.tools import tool

from core.departments.base import DepartmentSpec
from core.tools._kernel._shell_executor import shell_executor as _shell_executor
from core.tools._kernel._skills import load_skill as _load_skill
from core.tools._kernel._skills import skills_for
from core.tools._kernel.constants import SHELL_DEFAULT_TIMEOUT
from core.tools.descriptions.skills import TOOL_DESCRIPTION as SKILLS_DESCRIPTION


def build_department_tools(spec: DepartmentSpec, data_path: str) -> list:
    """Return [load_skill, shell_executor] bound to one department.

    Args:
        spec:       the department.
        data_path:  its view on this device.
    """
    names = tuple(s.name for s in skills_for(spec.name))
    if not names:
        raise RuntimeError(f"no skill is enabled for the {spec.name} department")
    SkillName = Literal[names]

    @tool("load_skill", description=SKILLS_DESCRIPTION["load_skill"])
    async def load_skill(name: SkillName) -> str:
        return _load_skill(name, spec.name)

    @tool("shell_executor", description=SKILLS_DESCRIPTION["shell_executor"])
    async def shell_executor(command: str, timeout: int = SHELL_DEFAULT_TIMEOUT) -> str:
        return await _shell_executor(command, spec.name, data_path, timeout)

    return [load_skill, shell_executor]
