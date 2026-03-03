import sys
import asyncio

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from dateutil import parser as dtparser
from fastapi import FastAPI, HTTPException
from .playwright_client import ensure_student_session, scan_assignments, read_assignment_by_id, perform_moodle_submission
from .instructor_playwright import ensure_instructor_session, create_assignment
from .schemas import (
    DraftByIdRequest, DraftRequest, DraftResponse, SubmissionRequest,
    CreateAssignmentRequest, CreateAssignmentResponse,
)
from .generator import generate_draft_by_id, generate_draft_from_instructions

app = FastAPI(title="Moodle Agent API")

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/init_session")
async def init_session():
    await ensure_student_session()
    return {"session": "ready"}

@app.get("/scan_assignments")
async def scan_assignments_endpoint():
    return await scan_assignments()

@app.get("/read_assignment/{assignment_id}")
async def read_assignment_by_id_endpoint(assignment_id: int):
    return await read_assignment_by_id(assignment_id)

@app.post("/draft_response", response_model=DraftResponse)
async def draft_response_endpoint(req: DraftByIdRequest):
    return await generate_draft_by_id(req.assignment_id)

@app.post("/draft_from_instructions", response_model=DraftResponse)
async def draft_from_instructions_endpoint(req: DraftRequest):
    return await generate_draft_from_instructions(
        title=req.assignment_title,
        instructions=req.instructions,
        submission_type=req.submission_type,
        due_date=req.due_date,
    )

@app.post("/submit_assignment")
async def submit_assignment_endpoint(req: SubmissionRequest):
    return await perform_moodle_submission(req.assignment_id, req.draft_content)


# ── Instructor endpoints ───────────────────────────────────────────

@app.post("/instructor/init_session")
async def instructor_init_session():
    """
    Validate (or refresh) the instructor Moodle session.
    Call this before using any other /instructor/* endpoints.
    """
    await ensure_instructor_session()
    return {"session": "ready", "role": "instructor"}


@app.post("/instructor/create_assignment", response_model=CreateAssignmentResponse)
async def instructor_create_assignment(req: CreateAssignmentRequest):
    """
    Create a new assignment in the configured Moodle course.

    Body:
      - title       : Assignment name
      - description : Instructions shown to students
      - due_date    : e.g. "2026-03-15T23:59" or "March 15 2026 11:59 PM"

    Submission type is always set to **Online text only** (no file upload).
    """
    try:
        due_dt = dtparser.parse(req.due_date, fuzzy=True)
    except Exception:
        raise HTTPException(
            status_code=422,
            detail=f"Could not parse due_date: '{req.due_date}'. "
                   "Use ISO-8601 or a human-readable date string.",
        )

    result = await create_assignment(
        title=req.title,
        description=req.description,
        due_date=due_dt,
    )
    return result