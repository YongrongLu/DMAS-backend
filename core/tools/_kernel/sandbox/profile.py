"""macOS Seatbelt profile for skill runs

Provides:
- air_gapped_profile:   a profile for sandbox-exec: read anywhere, write only to a temp dir, no network

Key constraints:
- reads stay global because the interpreter and site-packages live all over
  the disk; privacy comes from the executor's allow-list and output gate,
  the sandbox adds "no network" so a script can never send data anywhere
- credentials and shell history under the home directory stay unreadable
"""

import os


def air_gapped_profile(writable_dir: str) -> str:
    """Return the Seatbelt profile text.

    Args:
        writable_dir:   the only directory (besides /dev/null) the run may write to.
    """
    home = os.path.expanduser("~")
    return f"""(version 1)
(deny default)
(allow process-exec* process-fork sysctl-read mach-lookup file-map-executable)
(allow signal (target self))
(allow file-read*)
(deny file-read* (subpath "{home}/.ssh") (subpath "{home}/Library/Keychains")
      (literal "{home}/.zsh_history") (literal "{home}/.bash_history"))
(allow file-write* (subpath "{os.path.realpath(writable_dir)}") (literal "/dev/null"))
(deny network*)
"""
