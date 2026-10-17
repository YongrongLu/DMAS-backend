"""Tool descriptions for the file, bash and skill tools (_files, _bash, _skills).

Tools described:
- view_file         read numbered lines of a text file
- glob_tool         find files by pattern
- grep_tool         search file contents
- write_file        create or overwrite a workspace file
- str_replace       edit a workspace file
- bash              run a shell command in the workspace
- load_skill        read a skill's instructions
"""

TOOL_DESCRIPTION = {
    "view_file": (
        "Read a text file with line numbers, paged. Paths are relative to your workspace; your department's "
        "data is under data/. Binary files (xlsx, parquet, pdf, ...) are not shown - open them with code via bash.\n"
        "Parameters: path; offset (first line, default 1); limit (lines, default 200, max 500)."
    ),
    "glob_tool": (
        "Find files by glob pattern, e.g. pattern='**/*' path='data' to list all your data files with sizes.\n"
        "Parameters: pattern; path (directory, default the workspace)."
    ),
    "grep_tool": (
        "Search text files for a regex and return matching lines with file and line number.\n"
        "Parameters: pattern; path (file or directory, default the workspace); file_glob (e.g. '*.md'); ignore_case."
    ),
    "write_file": (
        "Create or overwrite a text file in your workspace, e.g. an analysis script. data/ is read-only.\n"
        "Parameters: path; content."
    ),
    "str_replace": (
        "Replace an exact snippet in a workspace file (unique unless replace_all), e.g. to fix a script.\n"
        "Parameters: path; old_str; new_str; replace_all."
    ),
    "bash": (
        "Run a shell command in your workspace (sandboxed, no network). `python` has pandas, numpy and openpyxl. "
        "Typical use: write a script with write_file, then run `python analysis.py`. Print only aggregated "
        "results - never print whole tables or raw records; large outputs are cut.\n"
        "Parameters: command; timeout (seconds, default 60)."
    ),
    "load_skill": (
        "Load the instructions of one skill from <AVAILABLE_SKILLS>: methods, pitfalls and code templates for a "
        "kind of task. Load the relevant skill before starting that kind of work.\n"
        "Parameters: name - the skill name exactly as listed."
    ),
}
