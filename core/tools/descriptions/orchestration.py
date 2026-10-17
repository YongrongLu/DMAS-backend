"""Tool descriptions for the orchestrator toolset (_orchestration).

Tools described:
- fanout_subagents      ask departments questions in parallel
- end_orchestration     finish and hand over to the final report
"""

TOOL_DESCRIPTION = {
    "fanout_subagents": (
        "Ask department agents questions IN PARALLEL. Each department runs on its own device, analyses only "
        "its own data and returns aggregated findings. `department` is a name from <ONLINE_DEPARTMENTS>. "
        "One task per department, all departments of a round in ONE call. Each question must be "
        "self-contained: the department cannot see the user's request, your plan or other departments' "
        "answers. State the exact scope (time periods, markets, products ...), what to measure and what to "
        "return. Results arrive in the next message."
    ),
    "end_orchestration": (
        "Finish. `response` is the handoff note for the final report: the key findings of each department "
        "with their numbers, the likely drivers, causes ruled out, recommended actions tied to evidence, "
        "and what is missing or unverified. Use only facts from department results."
    ),
}
