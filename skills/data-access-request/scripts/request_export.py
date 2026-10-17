"""data-access-request: a formal request for raw data, decided by the device's policy

The MVP policy refuses every raw (row-level) export; the result says so and
points to the aggregate analyses the department can run instead.

Usage:
    python skills/data-access-request/scripts/request_export.py --scope "full customer table" --reason "CEO request"
"""

from core.data import cli, output

SKILL = "data-access-request"


def build_parser():
    """Arguments of this skill."""
    parser = cli.build_parser(SKILL, "Request raw data from this device.")
    parser.add_argument("--scope", required=True, help="what data is requested")
    parser.add_argument("--reason", default="", help="why it is requested")
    return parser


def run(ctx: cli.Context, args) -> dict:
    """Refuse the export and offer aggregate analysis instead."""
    spec = ctx.spec
    return output.denied(
        SKILL, spec,
        f"raw {spec.record_label} export is not permitted on this device (requested: {args.scope.strip()[:120]})",
        notes=[
            "policy: row-level records never leave the device; only aggregate results do",
            f"what this device can answer instead: {spec.capability}",
            "e.g. " + " / ".join(spec.example_questions),
        ],
    )


if __name__ == "__main__":
    cli.run_skill(SKILL, build_parser(), run)
