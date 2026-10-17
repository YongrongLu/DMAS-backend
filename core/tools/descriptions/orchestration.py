"""Tool descriptions for the orchestrator toolset (_orchestration).

Tools described:
- make_plan             create the plan
- edit_plan             update phases
- delete_plan           remove a phase or the whole plan
- fanout_subagents      ask departments questions in parallel
- end_orchestration     finish and hand over to the final report
"""

TOOL_DESCRIPTION = {
    "make_plan": (
        "Create the plan for this request: 2-5 phases, e.g. decompose & dispatch, department analysis, "
        "cross-department follow-up, synthesis. Call once; then use edit_plan."
    ),
    "edit_plan": (
        "Update phases of the plan, e.g. mark one done and the next in_progress. "
        "Batch all changes in one call."
    ),
    "delete_plan": "Remove one phase by id, or the whole plan with delete_all=true.",
    "fanout_subagents": (
        "Ask department agents questions IN PARALLEL. Each department runs on its own device, analyses only "
        "its own data and returns aggregated findings. One task per department, all departments of a round "
        "in ONE call. Each question must be self-contained: the department cannot see the user's request, "
        "your plan or other departments' answers. State the exact periods (e.g. Feb-Apr 2011 vs Feb-Apr 2010), "
        "what to measure and what to return. Results arrive in the next message."
    ),
    "end_orchestration": (
        "Finish. `response` is the handoff note for the final report: the key findings of each department "
        "with their numbers, the likely drivers, causes ruled out, 2-4 recommended actions tied to evidence, "
        "and what is missing or unverified. Use only facts from department results."
    ),
}
