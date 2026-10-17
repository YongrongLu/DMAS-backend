"""Tool constants

Constants provided:
- PROJECT_ROOT:                 repository root; skill scripts run with it as cwd and PYTHONPATH
- SKILLS_DIR:                   where the skills live
- SKILL_FILE:                   the definition file of a skill
- SKILL_SCRIPTS_DIR:            the folder of a skill's runnable scripts
- ALLOWED_INTERPRETERS:         the only first tokens shell_executor accepts
- SHELL_OPERATOR_CHARS:         characters that form shell operators when unquoted
- SHELL_DEFAULT_TIMEOUT:        default seconds per skill run                    default 30
- SHELL_MAX_TIMEOUT:            max seconds per skill run                        default 120
- SKILL_OUTPUT_MAX_CHARS:       max chars of one result handed to the model      default 6000
- SHELL_STDERR_TAIL_CHARS:      stderr tail returned when a script fails         default 1500
- SHELL_MAX_COMMAND_CHARS:      max chars of one command                         default 2000
- SANDBOX_ENABLED:              wrap runs in the macOS air-gapped Seatbelt profile when available
"""

import os


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# _skills.py
SKILLS_DIR = os.path.join(PROJECT_ROOT, "skills")
SKILL_FILE = "SKILL.md"
SKILL_SCRIPTS_DIR = "scripts"

# _shell_executor.py
ALLOWED_INTERPRETERS = ("python", "python3")
SHELL_OPERATOR_CHARS = "();<>|&"
SHELL_DEFAULT_TIMEOUT = 30
SHELL_MAX_TIMEOUT = 120
SKILL_OUTPUT_MAX_CHARS = 6000
SHELL_STDERR_TAIL_CHARS = 1500
SHELL_MAX_COMMAND_CHARS = 2000
# 只在 macOS 上生效（sandbox-exec）；其他系统直接用普通子进程，安全性靠白名单和输出闸门
SANDBOX_ENABLED = True
