"""File tools: view, glob, grep, write, replace -- all checked against an AccessPolicy

Provides:
- view_file:        numbered lines of a text file, paged
- glob_tool:        find files by pattern
- grep_tool:        search file contents with a regex
- write_file:       create or overwrite a file in the workspace
- str_replace:      replace an exact snippet in a workspace file

Key constraints:
- every function returns text for the model and never raises; access
  violations come back as "Access denied: ..." / "Error: ..." messages
- binary files (xlsx, parquet, pdf, ...) are not dumped: view_file says how
  to open them with code instead
- outputs are capped (lines, chars, matches) to protect the model's context
"""

import fnmatch
import glob as globlib
import os
import re

from core.tools._kernel._access import AccessDenied, AccessPolicy
from core.tools._kernel.constants import (
    BINARY_SNIFF_BYTES,
    GLOB_MAX_RESULTS,
    GREP_MAX_FILE_BYTES,
    GREP_MAX_MATCHES,
    VIEW_DEFAULT_LINES,
    VIEW_MAX_CHARS,
    VIEW_MAX_LINES,
    WRITE_MAX_BYTES,
)

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".ipynb_checkpoints"}


def _is_binary(path: str) -> bool:
    with open(path, "rb") as f:
        chunk = f.read(BINARY_SNIFF_BYTES)
    return b"\0" in chunk


def _display(policy: AccessPolicy, real: str) -> str:
    """A path as the agent sees it: relative to the workspace, data/ for the department data."""
    if real.startswith(policy.workspace + os.sep) or real == policy.workspace:
        return os.path.relpath(real, policy.workspace)
    for root in policy.read_roots:
        if real.startswith(root + os.sep) or real == root:
            return os.path.join("data", os.path.relpath(real, root))
    return real


def view_file(policy: AccessPolicy, path: str, offset: int = 1, limit: int = VIEW_DEFAULT_LINES) -> str:
    """Numbered lines [offset, offset + limit) of a text file."""
    try:
        real = policy.check_read(path)
    except AccessDenied as exc:
        return str(exc)
    if not os.path.isfile(real):
        return f"Error: {path} is not a file" + (" (it is a directory; use glob_tool)" if os.path.isdir(real) else "")
    if _is_binary(real):
        size = os.path.getsize(real)
        return (f"{path} is a binary file ({size:,} bytes, extension {os.path.splitext(real)[1] or 'none'}). "
                "Open it with code via bash, e.g. pandas.read_excel / read_parquet, or a PDF/DOCX library.")

    offset, limit = max(1, int(offset)), max(1, min(int(limit), VIEW_MAX_LINES))
    lines, total, chars = [], 0, 0
    with open(real, encoding="utf-8", errors="replace") as f:
        for number, line in enumerate(f, start=1):
            total = number
            if number < offset or len(lines) >= limit:
                continue
            text = f"{number:>6}\t{line.rstrip()}"
            if chars + len(text) > VIEW_MAX_CHARS:
                lines.append(f"... [stopped at {VIEW_MAX_CHARS} chars; use offset to continue]")
                limit = len(lines)
                continue
            lines.append(text)
            chars += len(text) + 1
    shown_to = offset + len([l for l in lines if not l.startswith("...")]) - 1
    header = f"{_display(policy, real)} lines {offset}-{max(offset, shown_to)} of {total}"
    if shown_to < total:
        header += f"; next: offset={shown_to + 1}"
    return header + "\n" + "\n".join(lines)


def glob_tool(policy: AccessPolicy, pattern: str, path: str = ".") -> str:
    """Files matching a glob pattern (e.g. "**/*.csv") under path, with sizes."""
    try:
        base = policy.check_read(path)
    except AccessDenied as exc:
        return str(exc)
    if not os.path.isdir(base):
        return f"Error: {path} is not a directory"
    matches = []
    for found in sorted(globlib.glob(os.path.join(base, pattern), recursive=True)):
        if any(part in SKIP_DIRS for part in found.split(os.sep)) or not os.path.isfile(found):
            continue
        matches.append(f"{_display(policy, os.path.realpath(found))}  ({os.path.getsize(found):,} bytes)")
        if len(matches) >= GLOB_MAX_RESULTS:
            matches.append(f"... [stopped at {GLOB_MAX_RESULTS} results]")
            break
    return "\n".join(matches) if matches else f"No files match {pattern!r} under {path}"


def grep_tool(policy: AccessPolicy, pattern: str, path: str = ".", file_glob: str = "*",
              ignore_case: bool = False) -> str:
    """Lines matching a regex in text files under path (a file or a directory)."""
    try:
        base = policy.check_read(path)
        regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except AccessDenied as exc:
        return str(exc)
    except re.error as exc:
        return f"Error: invalid regex: {exc}"

    if os.path.isfile(base):
        files = [base]
    else:
        files = []
        for root, dirs, names in os.walk(base, followlinks=True):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            files.extend(os.path.join(root, n) for n in sorted(names) if fnmatch.fnmatch(n, file_glob))

    hits = []
    for file in files:
        real = os.path.realpath(file)
        if os.path.getsize(real) > GREP_MAX_FILE_BYTES or _is_binary(real):
            continue
        with open(real, encoding="utf-8", errors="replace") as f:
            for number, line in enumerate(f, start=1):
                if regex.search(line):
                    hits.append(f"{_display(policy, real)}:{number}: {line.rstrip()[:300]}")
                    if len(hits) >= GREP_MAX_MATCHES:
                        return "\n".join(hits + [f"... [stopped at {GREP_MAX_MATCHES} matches]"])
    return "\n".join(hits) if hits else f"No matches for {pattern!r}"


def write_file(policy: AccessPolicy, path: str, content: str) -> str:
    """Create or overwrite a text file inside the workspace."""
    try:
        real = policy.check_write(path)
    except AccessDenied as exc:
        return str(exc)
    data = str(content).encode("utf-8")
    if len(data) > WRITE_MAX_BYTES:
        return f"Error: content is {len(data):,} bytes; max {WRITE_MAX_BYTES:,}"
    os.makedirs(os.path.dirname(real), exist_ok=True)
    with open(real, "wb") as f:
        f.write(data)
    return f"Wrote {_display(policy, real)} ({len(data):,} bytes)"


def str_replace(policy: AccessPolicy, path: str, old_str: str, new_str: str, replace_all: bool = False) -> str:
    """Replace an exact snippet in a workspace file; it must be unique unless replace_all."""
    try:
        real = policy.check_write(path)
    except AccessDenied as exc:
        return str(exc)
    if not os.path.isfile(real):
        return f"Error: {path} does not exist"
    with open(real, encoding="utf-8") as f:
        text = f.read()
    count = text.count(old_str)
    if count == 0:
        return "Error: old_str not found; view the file and copy the exact text"
    if count > 1 and not replace_all:
        return f"Error: old_str appears {count} times; add surrounding lines to make it unique or set replace_all"
    with open(real, "w", encoding="utf-8") as f:
        f.write(text.replace(old_str, new_str) if replace_all else text.replace(old_str, new_str, 1))
    return f"Replaced {count if replace_all else 1} occurrence(s) in {_display(policy, real)}"
