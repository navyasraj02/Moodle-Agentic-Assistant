import sys
import asyncio

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI
from .playwright_client import ensure_student_session, scan_assignments, read_assignment_by_id, perform_moodle_submission
from .schemas import DraftByIdRequest, DraftResponse, SubmissionRequest
from .generator import generate_draft_by_id  

app = FastAPI(title="Moodle Student Agent (MVP)")

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

@app.post("/submit_assignment")
async def submit_assignment_endpoint(req: SubmissionRequest):
    return await perform_moodle_submission(req.assignment_id, req.draft_content)