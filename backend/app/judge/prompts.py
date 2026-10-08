from __future__ import annotations

from backend.app.judge.schemas import PROBLEM_TYPES, PROBLEM_TYPE, RECURRING, SAME_PROBLEM, UNRESOLVED, WORTH_BUILDING

QUESTIONS: dict[str, dict] = {
    SAME_PROBLEM: {
        "type": "noul",
        "instructions": (
            "Are these GitHub artifacts manifestations of the same underlying user problem?"
        ),
        "criteria": {
            "true": (
                "They describe the same underlying unmet need or defect, "
                "even when wording and surface details differ."
            ),
            "false": (
                "They are materially different problems and only appear similar "
                "because of vocabulary or context."
            ),
        },
    },
    RECURRING: {
        "type": "noul",
        "instructions": (
            "Do these cases represent a persistent, independent, recurring real problem "
            "rather than a one-off incident or the same person filing repeatedly?"
        ),
        "criteria": {
            "true": (
                "Multiple independent authors report this over a meaningful time span, "
                "or it reappears across issues, discussions, and pull requests."
            ),
            "false": (
                "It is driven by a single author, a single event, or a short-lived "
                "glitch with no independent recurrence."
            ),
        },
    },
    UNRESOLVED: {
        "type": "noul",
        "instructions": "Is the underlying problem still unresolved in this repository?",
        "criteria": {
            "true": (
                "There is no convincing evidence that the underlying problem has been solved."
            ),
            "false": (
                "There is convincing evidence that the problem has been solved, "
                "merged, released, or is no longer relevant."
            ),
        },
    },
    WORTH_BUILDING: {
        "type": "score",
        "instructions": (
            "How valuable would it be for a contributor to build a solution for this problem?"
        ),
        "criteria": [
            "Negligible opportunity",
            "Some opportunity but weak",
            "Clearly worthwhile",
            "Exceptional opportunity",
        ],
    },
    PROBLEM_TYPE: {
        "type": "choice",
        "instructions": "What kind of opportunity is this?",
        "criteria": {
            "bug_fix": "A recurring defect or incorrect behavior",
            "missing_feature": "A missing capability users repeatedly request",
            "developer_experience": "A repeated developer workflow or DX problem",
            "performance": "A recurring speed, memory, or scaling problem",
            "integration": "A missing or inadequate integration",
            "documentation": "A recurring documentation/discoverability problem",
            "workflow": "A repeated workflow that users currently handle manually",
            "architecture": "A structural limitation requiring deeper redesign",
            "other": "Does not fit the above categories",
        },
    },
}
