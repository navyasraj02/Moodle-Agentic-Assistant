import json
import httpx
from .playwright_client import read_assignment_by_id
from .schemas import ReadAssignmentResponse, DraftResponse
from .config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TEMPERATURE


# ── Ollama helper ──────────────────────────────────────────────────
async def _ollama_chat(messages: list[dict], temperature: float | None = None) -> str:
    """Send a chat-completion request to the local Ollama server."""
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature or OLLAMA_TEMPERATURE},
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()["message"]["content"]


# ── Public entry-point (used by FastAPI + agent) ──────────────────
async def generate_draft_by_id(assignment_id: int) -> DraftResponse:
    """
    Orchestrator: fetch assignment from Moodle, then generate a draft via LLM.
    """
    assignment_data = await read_assignment_by_id(assignment_id)

    if assignment_data.get("status") == "closed":
        return DraftResponse(
            action_plan=["None"],
            checklist=["N/A"],
            draft="Cannot generate draft: This assignment is closed.",
        )

    data = ReadAssignmentResponse(**assignment_data)
    return await generate_draft_content(data)


async def generate_draft_from_instructions(
    title: str,
    instructions: str,
    submission_type: str | None = None,
    due_date: str | None = None,
) -> DraftResponse:
    """
    Generate a draft when you already have instructions text (no Moodle fetch).
    Useful for the agent workflow where read_assignment was already called.
    """
    return await _llm_draft(title, instructions, submission_type, due_date)


# ── Core LLM drafting logic ──────────────────────────────────────
async def generate_draft_content(data: ReadAssignmentResponse) -> DraftResponse:
    """Generate a draft from a ReadAssignmentResponse via LLM."""
    return await _llm_draft(
        title=data.title,
        instructions=data.instructions,
        submission_type=data.submission_type,
        due_date=data.due_date,
    )


async def _llm_draft(
    title: str,
    instructions: str,
    submission_type: str | None,
    due_date: str | None,
) -> DraftResponse:
    """
    Two-step LLM pipeline:
      1. Plan  → action_plan + checklist (JSON)
      2. Draft → the actual answer text
    """
    # ---- Step 1: planning ----
    plan_prompt = (
        "You are a diligent university student assistant.\n"
        "Given the assignment below, produce a JSON object with two keys:\n"
        '  "action_plan": a list of 3-6 short action steps to complete the assignment,\n'
        '  "checklist": a list of 3-6 self-check items (word count, format, tone, etc.).\n'
        "Return ONLY valid JSON, no markdown fences.\n\n"
        f"Title: {title}\n"
        f"Instructions: {instructions}\n"
        f"Submission type: {submission_type or 'unknown'}\n"
        f"Due date: {due_date or 'N/A'}\n"
    )
    plan_raw = await _ollama_chat(
        [{"role": "user", "content": plan_prompt}],
        temperature=0.3,
    )
    try:
        plan = json.loads(plan_raw)
    except json.JSONDecodeError:
        # Try to extract JSON from the response
        import re
        m = re.search(r"\{.*\}", plan_raw, re.S)
        plan = json.loads(m.group()) if m else {}

    action_plan = plan.get("action_plan", ["Read requirements", "Draft text", "Self-check"])
    checklist = plan.get("checklist", ["Meets word count", "Follows format", "Professional tone"])

    # ---- Step 2: drafting ----
    draft_prompt = (
        "You are a university student writing an assignment submission.\n"
        "Write a clear, well-structured answer for the assignment below.\n"
        "Use an academic but natural tone. Be concise yet thorough.\n\n"
        f"Title: {title}\n"
        f"Instructions: {instructions}\n"
        f"Submission type: {submission_type or 'online text'}\n\n"
        "Action plan to follow:\n"
        + "\n".join(f"  - {s}" for s in action_plan)
        + "\n\nWrite the full answer now."
    )
    draft_text = await _ollama_chat(
        [{"role": "user", "content": draft_prompt}],
        temperature=OLLAMA_TEMPERATURE,
    )

    return DraftResponse(
        action_plan=action_plan,
        checklist=checklist,
        draft=draft_text.strip(),
    )