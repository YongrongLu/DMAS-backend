"""Tool descriptions for the plan toolset (_plan).

Tools described:
- make_plan             create the plan
- edit_plan             update phases
- delete_plan           remove a phase or the whole plan
"""

TOOL_DESCRIPTION = {
    "make_plan": (
        "Create a plan of 2-5 phases for the current task. Call once; then keep it current with edit_plan."
    ),
    "edit_plan": (
        "Update phases of the plan, e.g. mark one done and the next in_progress. "
        "Batch all changes in one call."
    ),
    "delete_plan": "Remove one phase by id, or the whole plan with delete_all=true.",
}
