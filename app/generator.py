from .playwright_client import read_assignment_by_id
from .schemas import ReadAssignmentResponse, DraftResponse

async def generate_draft_by_id(assignment_id: int) -> DraftResponse:
    """
    Orchestrator function: Fetches data from Moodle and generates a draft.
    """
    # 1. Fetch data using your existing Playwright client
    assignment_data = await read_assignment_by_id(assignment_id)
    
    # 2. Check status
    if assignment_data.get("status") == "closed":
        return DraftResponse(
            action_plan=["None"],
            checklist=["N/A"],
            draft="Cannot generate draft: This assignment is closed."
        )

    # 3. Convert to Pydantic for internal handling
    data = ReadAssignmentResponse(**assignment_data)
    
    # 4. Perform the generation logic (Free LLM or Template)
    return await generate_draft_content(data)

async def generate_draft_content(data: ReadAssignmentResponse) -> DraftResponse:
    """
    The actual AI/Template logic.
    """
    # ... (Your logic from before goes here) ...
    return DraftResponse(
        action_plan=["Read requirements", "Draft text"],
        checklist=["Verified title", "Verified type"],
        draft=f"Draft for {data.title}: [Content here]"
    )