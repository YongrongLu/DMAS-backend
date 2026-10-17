"""Command-line plumbing shared by every skill script

A skill script only declares its arguments and a run(ctx, args) function;
this module reads the department and data path from the environment set by
shell_executor, loads the view, turns exceptions into results and prints
the result.

Provides:
- Context:              the department, its view and the data path of one run
- SkillArgumentParser:  argparse that reports usage errors as skill results
- add_* helpers:        the common arguments (metric, group-by, filters, periods, limit)
- load_context:         build the Context from ENV_DEPARTMENT / ENV_DATA_PATH
- parse_filters:        parse every --filter of a run
- run_skill:            parse, run, emit; the main() of every skill script

Key constraints:
- the model never passes a data path: it comes from the environment only
- every outcome is one JSON line on stdout; the exit code is 0 for ok and
  denied, 1 for error
"""

import argparse
import os
import sys
from dataclasses import dataclass

import pandas as pd

from core.data import filters as filters_mod
from core.data import output
from core.data.constants import DEFAULT_LIMIT, ENV_DATA_PATH, ENV_DEPARTMENT
from core.data.errors import PolicyDenied, SkillError
from core.data.loader import load_frame
from core.departments import get_department
from core.departments.base import DepartmentSpec


@dataclass(frozen=True)
class Context:
    """One skill run: the department, its view and where the view lives."""
    spec: DepartmentSpec
    df: pd.DataFrame
    data_path: str

    @property
    def dates(self) -> pd.Series:
        """The date column of the whole view."""
        return self.df[self.spec.date_column]


class SkillArgumentParser(argparse.ArgumentParser):
    """argparse that raises SkillError instead of printing usage and exiting."""

    def error(self, message):
        raise SkillError(f"{message}. usage: {self.format_usage().strip()}")

    def print_help(self, file=None):
        raise SkillError(f"see the skill's SKILL.md for usage. {self.format_usage().strip()}")


def build_parser(skill: str, description: str) -> SkillArgumentParser:
    """A parser for one skill script."""
    return SkillArgumentParser(prog=skill, description=description, add_help=False)


def add_metric(parser, *, many: bool = False, required: bool = True) -> None:
    """--metric NAME, or --metrics A,B when many."""
    if many:
        parser.add_argument("--metrics", required=required, help="comma-separated metric names")
    else:
        parser.add_argument("--metric", required=required, help="metric name")


def add_group_by(parser) -> None:
    """--group-by DIMENSION, or a comma-separated list where a skill allows several."""
    parser.add_argument("--group-by", default="", help="dimension(s) to group by")


def add_filters(parser) -> None:
    """--filter "<dimension>=<value>", repeatable."""
    parser.add_argument("--filter", action="append", default=[], help="row filter, repeatable")


def add_range(parser) -> None:
    """--start / --end, each YYYY-MM or YYYY-MM-DD, both inclusive."""
    parser.add_argument("--start", default="", help="first day or month, inclusive")
    parser.add_argument("--end", default="", help="last day or month, inclusive")


def add_periods(parser) -> None:
    """--period-a / --period-b as START:END."""
    parser.add_argument("--period-a", required=True, help="baseline period START:END")
    parser.add_argument("--period-b", required=True, help="period under review START:END")


def add_limit(parser, default: int = DEFAULT_LIMIT) -> None:
    """--limit N."""
    parser.add_argument("--limit", type=int, default=default, help="max rows to show")


def split_list(text: str) -> list[str]:
    """"a, b" -> ["a", "b"]; empty text -> []."""
    return [part.strip() for part in str(text or "").split(",") if part.strip()]


def load_context() -> Context:
    """Build the run's Context from the environment.

    Raises:
        SkillError: when the environment is incomplete or the view is unusable.
    """
    name = os.environ.get(ENV_DEPARTMENT, "")
    path = os.environ.get(ENV_DATA_PATH, "")
    if not name or not path:
        raise SkillError(f"{ENV_DEPARTMENT} and {ENV_DATA_PATH} must be set; run skills through shell_executor")
    try:
        spec = get_department(name)
    except KeyError as exc:
        raise SkillError(str(exc)) from None
    return Context(spec=spec, df=load_frame(spec, path), data_path=path)


def parse_filters(ctx: Context, texts) -> list:
    """Parse every --filter of a run."""
    return [filters_mod.parse_filter(text, ctx.spec, ctx.df) for text in texts]


def run_skill(skill: str, parser: SkillArgumentParser, run, argv=None) -> dict:
    """Parse arguments, run the skill and print its result.

    Args:
        skill:      the skill name, written into the result.
        parser:     the skill's argument parser.
        run:        run(ctx, args) -> result dict.
        argv:       arguments; defaults to sys.argv[1:].

    Returns:
        the printed result (handy for tests).
    """
    spec = None
    try:
        args = parser.parse_args(argv)
        ctx = load_context()
        spec = ctx.spec
        result = run(ctx, args)
    except PolicyDenied as exc:
        result = output.denied(skill, spec, str(exc))
    except SkillError as exc:
        result = output.error(skill, str(exc), spec)

    output.emit(result)
    if argv is None:
        sys.exit(1 if result["status"] == "error" else 0)
    return result
