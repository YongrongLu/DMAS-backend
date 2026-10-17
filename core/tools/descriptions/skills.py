"""Tool descriptions for the department toolset (_skills, _shell_executor).

Tools described:
- load_skill        read a skill's instructions before using it
- shell_executor    run one skill script
"""

TOOL_DESCRIPTION = {
    "load_skill": (
        "Load the instructions of one analysis skill from <AVAILABLE_SKILLS>. "
        "Call it once per skill before running that skill's script; it returns the usage, the "
        "arguments and how to read the result.\n"
        "Parameters:\n"
        "- name: the skill name, exactly as listed"
    ),
    "shell_executor": (
        "Run one skill script on this device and return its JSON result.\n"
        "The command MUST be: python skills/<skill>/scripts/<script>.py [args] - copy the usage line "
        "from the loaded skill. Exactly one script per call: no pipes, redirects, ; or &&. "
        "Quote values with spaces, e.g. --filter \"category=Lighting & Candles\". "
        "Never pass a data file path; the device provides it.\n"
        "Any other command, and any attempt to read or print the data file, is denied and logged.\n"
        "Parameters:\n"
        "- command: the script command\n"
        "- timeout: seconds, default 30\n"
        "Result: status ok (columns, rows, notes, source), error (fix the arguments and retry once), "
        "or denied (do not retry; report the denial)."
    ),
}
