"""
AutoGen-compatible tool functions.

Each function is a thin wrapper around the existing Playwright client
and generator logic.  They are called **in-process** (no HTTP round-trip)
so the FastAPI server does NOT need to be running when the agent is used.
"""

from __future__ import annotations
import json
from typing import Annotated

from .playwright_client import (
    ensure_student_session,
    scan_assignments,
    read_assignment_by_id,
    perform_moodle_submission,
)
from .generator import generate_draft_from_instructions


# ── 1. Initialise Moodle session ──────────────────────────────────
async def init_session() -> str:
    """Ensure the Moodle browser session is ready. Call this first."""
    await ensure_student_session()
    return json.dumps({"session": "ready"})


# ── 2. Scan assignments ──────────────────────────────────────────
async def tool_scan_assignments() -> str:
    """
    Scan the Moodle course and return a JSON list of assignments.
    Each item has: assignment_id, title, due_date, link, status (open/closed).
    """
    result = await scan_assignments()
    return json.dumps(result, indent=2)


# ── 3. Read a single assignment ──────────────────────────────────
async def tool_read_assignment(
    assignment_id: Annotated[int, "The Moodle assignment ID to read"],
) -> str:
    """
    Open a specific assignment page and return its details as JSON.
    Includes: title, instructions, due_date, status, submission_type, can_submit.
    """
    result = await read_assignment_by_id(assignment_id)
    return json.dumps(result, indent=2)


# ── 4. Generate a draft answer ───────────────────────────────────
async def tool_generate_draft(
    title: Annotated[str, "Assignment title"],
    instructions: Annotated[str, "Assignment instructions text"],
    submission_type: Annotated[str, "Submission type: file / text / both / unknown"] = "text",
    due_date: Annotated[str, "Due date string or empty"] = "",
) -> str:
    """
    Use the local LLM to generate an action plan, checklist, and draft answer.
    Returns JSON with keys: action_plan, checklist, draft.
    """
    resp = await generate_draft_from_instructions(
        title=title,
        instructions=instructions,
        submission_type=submission_type or None,
        due_date=due_date or None,
    )
    return resp.model_dump_json(indent=2)


# ── 5. Submit the assignment (requires prior human approval) ─────
async def tool_submit_assignment(
    assignment_id: Annotated[int, "The Moodle assignment ID"],
    draft_content: Annotated[str, "The final text to submit"],
) -> str:
    """
    Submit the draft content to Moodle for the given assignment.
    IMPORTANT: Only call this AFTER the human user has approved the draft.
    """
    result = await perform_moodle_submission(assignment_id, draft_content)
    return json.dumps(result, indent=2)
