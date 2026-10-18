"""Tool constants

Constants provided:
- PROJECT_ROOT:                 repository root
- SKILLS_DIR:                   where the skills live
- WORKSPACES_DIR:               parent of every agent workspace
- SKILL_FILE:                   the definition file of a skill
- DATA_LINK:                    name of the read-only data link inside a department workspace
- VIEW_DEFAULT_LINES:           lines returned by view_file by default                 default 200
- VIEW_MAX_LINES:               max lines per view_file call                           default 500
- VIEW_MAX_CHARS:               max chars per view_file call                           default 12000
- BINARY_SNIFF_BYTES:           bytes read to detect a binary file                     default 4096
- GLOB_MAX_RESULTS:             max paths returned by glob_tool                        default 200
- GREP_MAX_MATCHES:             max matching lines returned by grep_tool               default 100
- GREP_MAX_FILE_BYTES:          files larger than this are skipped by grep_tool        default 20 MB
- WRITE_MAX_BYTES:              max size of one write_file                             default 1 MB
- BASH_DEFAULT_TIMEOUT:         default seconds per bash command                       default 60
- BASH_MAX_TIMEOUT:             max seconds per bash command                           default 300
- BASH_MAX_OUTPUT_CHARS:        max chars of stdout + stderr returned to the model     default 3000
- SANDBOX_ENABLED:              wrap bash in a macOS Seatbelt profile when available
- SENSITIVE_HOME_PATHS:         home paths no tool or command may read
"""

import os


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SKILLS_DIR = os.path.join(PROJECT_ROOT, "skills")
WORKSPACES_DIR = os.path.join(PROJECT_ROOT, "workspaces")

# _skills.py
SKILL_FILE = "SKILL.md"

# _access.py：部门工作区里指向本部门 shared/ 的只读链接
DATA_LINK = "data"

# _files.py
VIEW_DEFAULT_LINES = 200
VIEW_MAX_LINES = 500
VIEW_MAX_CHARS = 12000
BINARY_SNIFF_BYTES = 4096
GLOB_MAX_RESULTS = 200
GREP_MAX_MATCHES = 100
GREP_MAX_FILE_BYTES = 20 * 1024 * 1024
WRITE_MAX_BYTES = 1024 * 1024

# _bash.py
BASH_DEFAULT_TIMEOUT = 60
BASH_MAX_TIMEOUT = 300
BASH_MAX_OUTPUT_CHARS = 3000
# macOS keeps Seatbelt; Windows/WSL/Linux use Docker. Missing isolation fails closed.
SANDBOX_ENABLED = True
SENSITIVE_HOME_PATHS = (".ssh", "Library/Keychains", ".zsh_history", ".bash_history", ".aws", ".config/gcloud")
