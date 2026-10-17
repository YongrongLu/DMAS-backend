"""File, bash and skill tool definitions, bound to one agent's AccessPolicy.

Lightweight wrappers binding kernel implementations to the @tool decorator.

Tools provided:
    ├── view_file                       read numbered lines of a text file
    ├── glob_tool                       find files by pattern
    ├── grep_tool                       search file contents
    ├── write_file                      create or overwrite a workspace file
    ├── str_replace                     edit a workspace file
    ├── bash                            run a shell command (only when with_bash)
    └── load_skill                      read a skill's instructions (only when skills_for is set)

Provides:
- build_file_tools:     the tools above, bound to one policy
"""

from langchain_core.tools import tool

from core.tools._kernel import _bash, _files
from core.tools._kernel._access import AccessPolicy
from core.tools._kernel._skills import load_skill as _load_skill
from core.tools._kernel.constants import BASH_DEFAULT_TIMEOUT, VIEW_DEFAULT_LINES
from core.tools.descriptions.files import TOOL_DESCRIPTION


def build_file_tools(policy: AccessPolicy, *, with_bash: bool, skills_for: str | None = None) -> list:
    """File tools bound to a policy, plus bash and load_skill when asked.

    Args:
        policy:         where the agent may read and write.
        with_bash:      include the bash tool.
        skills_for:     the department whose skills load_skill may load; None leaves load_skill out.
    """

    @tool("view_file", description=TOOL_DESCRIPTION["view_file"])
    async def view_file(path: str, offset: int = 1, limit: int = VIEW_DEFAULT_LINES) -> str:
        return _files.view_file(policy, path, offset, limit)

    @tool("glob_tool", description=TOOL_DESCRIPTION["glob_tool"])
    async def glob_tool(pattern: str, path: str = ".") -> str:
        return _files.glob_tool(policy, pattern, path)

    @tool("grep_tool", description=TOOL_DESCRIPTION["grep_tool"])
    async def grep_tool(pattern: str, path: str = ".", file_glob: str = "*", ignore_case: bool = False) -> str:
        return _files.grep_tool(policy, pattern, path, file_glob, ignore_case)

    @tool("write_file", description=TOOL_DESCRIPTION["write_file"])
    async def write_file(path: str, content: str) -> str:
        return _files.write_file(policy, path, content)

    @tool("str_replace", description=TOOL_DESCRIPTION["str_replace"])
    async def str_replace(path: str, old_str: str, new_str: str, replace_all: bool = False) -> str:
        return _files.str_replace(policy, path, old_str, new_str, replace_all)

    tools = [view_file, glob_tool, grep_tool, write_file, str_replace]

    if with_bash:
        @tool("bash", description=TOOL_DESCRIPTION["bash"])
        async def bash(command: str, timeout: int = BASH_DEFAULT_TIMEOUT) -> str:
            return await _bash.bash(policy, command, timeout)
        tools.append(bash)

    if skills_for is not None:
        @tool("load_skill", description=TOOL_DESCRIPTION["load_skill"])
        async def load_skill(name: str) -> str:
            return _load_skill(name, skills_for)
        tools.append(load_skill)

    return tools
