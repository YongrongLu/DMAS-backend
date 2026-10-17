"""Skill registry: discover skills, filter them by department, load one

A skill is a folder under skills/ with a SKILL.md and a scripts/ folder:

    skills/time-trend/
    ├── SKILL.md          frontmatter (name, description, optional departments) + instructions
    └── scripts/          optional helper scripts the instructions refer to

Provides:
- SkillInfo:            one parsed skill
- parse_skill:          parse one skill folder
- discover_skills:      every skill under a skills directory
- skills_for:          the skills one department may use
- render_skill_index:   the <AVAILABLE_SKILLS> block for a department's system prompt, with each script path
- load_skill:           a skill's instructions and scripts, as a JSON tool result

Key constraints:
- the system prompt only carries name + description; the full SKILL.md
  reaches the context when the agent calls load_skill (progressive disclosure)
- frontmatter supports `key: value` lines and `departments: [a, b]` lists only
- all tool results are JSON strings with status ok or error, never raised
"""

import json
import os
from dataclasses import dataclass
from functools import lru_cache

from core.tools._kernel.constants import PROJECT_ROOT, SKILL_FILE, SKILLS_DIR

SKILL_SCRIPTS_DIR = "scripts"


@dataclass(frozen=True)
class SkillInfo:
    """One skill.

    Attributes:
        name:           the skill name, equal to its folder name.
        description:    one line telling the agent when to use it.
        departments:    departments allowed to use it.
        body:           SKILL.md without the frontmatter.
        scripts:        runnable script paths relative to the project root.
    """
    name: str
    description: str
    departments: tuple[str, ...]
    body: str
    scripts: tuple[str, ...]


def _parse_frontmatter(text: str, path: str) -> tuple[dict, str]:
    """Split SKILL.md into its frontmatter dict and body."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path}: SKILL.md must start with a --- frontmatter block")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise ValueError(f"{path}: frontmatter is not closed with ---") from None

    meta = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise ValueError(f"{path}: bad frontmatter line {line!r}")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            value = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        meta[key.strip()] = value
    return meta, "\n".join(lines[end + 1:]).strip()


def parse_skill(skill_dir: str, project_root: str = PROJECT_ROOT) -> SkillInfo:
    """Parse one skill folder.

    Raises:
        ValueError: when SKILL.md is missing, malformed, or names another folder.
    """
    path = os.path.join(skill_dir, SKILL_FILE)
    with open(path, encoding="utf-8") as f:
        meta, body = _parse_frontmatter(f.read(), path)

    name = meta.get("name", "")
    if name != os.path.basename(skill_dir):
        raise ValueError(f"{path}: name {name!r} must equal the folder name")
    departments = meta.get("departments", ["all"])
    if not isinstance(departments, list):
        departments = [departments]
    if not meta.get("description"):
        raise ValueError(f"{path}: description is required")

    scripts_dir = os.path.join(skill_dir, SKILL_SCRIPTS_DIR)
    scripts = tuple(
        os.path.relpath(os.path.join(scripts_dir, f), project_root)
        for f in sorted(os.listdir(scripts_dir)) if f.endswith(".py")
    ) if os.path.isdir(scripts_dir) else ()
    return SkillInfo(name, meta["description"], tuple(departments), body, scripts)


@lru_cache(maxsize=4)
def discover_skills(skills_dir: str = SKILLS_DIR, project_root: str = PROJECT_ROOT) -> dict[str, SkillInfo]:
    """Every skill under skills_dir, by name; folders without SKILL.md are ignored."""
    skills = {}
    for entry in sorted(os.listdir(skills_dir)):
        folder = os.path.join(skills_dir, entry)
        if os.path.isfile(os.path.join(folder, SKILL_FILE)):
            info = parse_skill(folder, project_root)
            skills[info.name] = info
    return skills


def skills_for(department: str, skills_dir: str = SKILLS_DIR, project_root: str = PROJECT_ROOT) -> list[SkillInfo]:
    """The skills a department may use, sorted by name."""
    return [s for s in discover_skills(skills_dir, project_root).values()
            if "all" in s.departments or department in s.departments]


def render_skill_index(department: str, skills_dir: str = SKILLS_DIR) -> str:
    """The skill list for a department's system prompt: names and descriptions only."""
    lines = []
    for s in skills_for(department, skills_dir):
        lines.append(f"  - {s.name}: {s.description}")
        lines.extend(f"      script: python {script}" for script in s.scripts)
    return "<AVAILABLE_SKILLS>\n" + "\n".join(lines) + "\n</AVAILABLE_SKILLS>"


def load_skill(name: str, department: str, skills_dir: str = SKILLS_DIR) -> str:
    """Return a skill's instructions and scripts.

    Args:
        name:           the skill to load.
        department:     the calling department; it may only load its own skills.
        skills_dir:     where the skills live.

    Returns:
        JSON with status ok, the skill body and its scripts, or status error
        listing the skills this department can load.
    """
    available = {s.name: s for s in skills_for(department, skills_dir)}
    skill = available.get(str(name).strip())
    if skill is None:
        return json.dumps({
            "status": "error",
            "tool_name": "load_skill",
            "message": f"skill {name!r} is not available to the {department} department; "
                       f"available: {sorted(available)}",
        }, ensure_ascii=False)

    return json.dumps({
        "status": "ok",
        "skill": skill.name,
        "content": skill.body,
        "scripts": list(skill.scripts),
    }, ensure_ascii=False)
