"""Exceptions raised by the data layer and turned into skill results by cli.run_skill

Classes provided:
- SkillError:       the request is invalid (unknown metric, bad period, ...); becomes status "error"
- PolicyDenied:     the request would expose restricted data; becomes status "denied"
"""


class SkillError(ValueError):
    """The skill request is invalid; the message tells the agent how to fix it."""


class PolicyDenied(Exception):
    """The skill request would expose data that must not leave the device."""
