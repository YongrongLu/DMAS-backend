"""Terminal output of the demo

Each process prints what the audience should see on its screen: the
orchestrator shows the plan, the dispatched questions and the final report;
a department shows the skills it runs and its conclusion.

Provides:
- say:          one tagged line
- block:        a titled block of lines
- preview:      a single-line preview of a long text
"""

import sys

COLORS = {"cyan": "36", "green": "32", "yellow": "33", "red": "31", "magenta": "35", "grey": "90", "bold": "1"}


def _paint(text: str, color: str | None) -> str:
    """Wrap text in an ANSI color when stdout is a terminal."""
    if not color or not sys.stdout.isatty():
        return text
    return f"\033[{COLORS[color]}m{text}\033[0m"


def say(tag: str, text: str, color: str | None = None) -> None:
    """Print one line: "[tag] text"."""
    print(f"{_paint(f'[{tag}]', color)} {text}", flush=True)


def block(title: str, lines: list[str], color: str | None = "cyan") -> None:
    """Print a titled block."""
    print(_paint(f"┌─ {title}", color), flush=True)
    for line in lines:
        print(_paint("│ ", color) + line, flush=True)
    print(_paint("└─", color), flush=True)


def preview(text: str, limit: int = 160) -> str:
    """The text on one line, cut at limit chars."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit] + "…"
