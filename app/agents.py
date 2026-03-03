"""
Moodle Student Agent — scripted pipeline with LLM drafting.

The pipeline orchestrates each step deterministically (no LLM planning needed).
The LLM is used ONLY for generating the draft answer.
Human-in-the-loop: user must APPROVE the draft before submission.
"""

from __future__ import annotations
import json

from .playwright_client import (
    ensure_student_session,
    scan_assignments,
    read_assignment_by_id,
    perform_moodle_submission,
)
from .generator import generate_draft_from_instructions


def _separator(title: str = "") -> None:
    print(f"\n{'='*60}")
    if title:
        print(f"  >> {title}")
        print("=" * 60)


def _pick_best_assignment(assignments: list[dict]) -> dict | None:
    """Pick the best open assignment: nearest due date, or first open."""
    open_ones = [a for a in assignments if a.get("status") == "open"]
    if not open_ones:
        return None
    # Prefer ones with a due date (sorted by due_date string — Moodle dates sort OK)
    with_due = [a for a in open_ones if a.get("due_date")]
    if with_due:
        return with_due[0]
    return open_ones[0]


async def run_agent_loop(task: str | None = None) -> None:
    """
    Run the full Moodle student agent pipeline:
      1. Init session
      2. Scan assignments
      3. Pick best open assignment
      4. Read assignment details
      5. Generate draft (LLM)
      6. Self-check
      7. Human approval loop (APPROVE / revise)
      8. Submit
    """

    # ── Step 1: Init session ──────────────────────────────────────
    _separator("Step 1: Initializing Moodle session")
    await ensure_student_session()
    print("  Session ready.")

    # ── Step 2: Scan assignments ──────────────────────────────────
    _separator("Step 2: Scanning assignments")
    scan_result = await scan_assignments()
    assignments = scan_result.get("assignments", [])
    print(f"  Course: {scan_result.get('course')}")
    print(f"  Found {len(assignments)} assignment(s):\n")
    for a in assignments:
        status_icon = "OPEN" if a["status"] == "open" else "CLOSED"
        due = a.get("due_date") or "No due date"
        print(f"    [{status_icon}] #{a['assignment_id']}  {a['title']}  (Due: {due})")

    # ── Step 3: Pick the best assignment ──────────────────────────
    _separator("Step 3: Picking best assignment")
    target = _pick_best_assignment(assignments)
    if not target:
        print("  No open assignments found. Nothing to do.")
        return
    print(f"  Selected: #{target['assignment_id']} — {target['title']}")

    # ── Step 4: Read assignment details ───────────────────────────
    _separator("Step 4: Reading assignment details")
    details = await read_assignment_by_id(target["assignment_id"])
    print(f"  Title:           {details.get('title')}")
    print(f"  Due date:        {details.get('due_date', 'N/A')}")
    print(f"  Status:          {details.get('status')}")
    print(f"  Submission type: {details.get('submission_type', 'unknown')}")
    print(f"  Can submit:      {details.get('can_submit')}")
    print(f"  Instructions:    {details.get('instructions') or '(none found)'}")

    instructions = details.get("instructions", "")
    if not instructions:
        print("\n  WARNING: No instructions found on the page.")
        print("  The agent will try to draft based on the title alone.")

    if not details.get("can_submit"):
        print("\n  Cannot submit to this assignment (no submit button found).")
        print("  Exiting.")
        return

    # ── Step 5: Generate draft (LLM) ─────────────────────────────
    assignment_id = details["assignment_id"]
    title = details.get("title", "")
    sub_type = details.get("submission_type", "text")
    due_date = details.get("due_date", "")

    _separator("Step 5: Generating draft with LLM")
    print("  Calling Ollama... (this may take a minute)")

    draft_resp = await generate_draft_from_instructions(
        title=title,
        instructions=instructions,
        submission_type=sub_type,
        due_date=due_date,
    )

    # ── Step 6: Self-check ────────────────────────────────────────
    _separator("Step 6: Self-check")
    print("  Action plan:")
    for step in draft_resp.action_plan:
        print(f"    - {step}")
    print("\n  Checklist:")
    for item in draft_resp.checklist:
        print(f"    [x] {item}")

    # ── Step 7: Present draft + approval loop ─────────────────────
    draft_text = draft_resp.draft

    while True:
        _separator("DRAFT FOR REVIEW")
        print(draft_text)
        _separator()
        print("\n  Options:")
        print("    APPROVE  — submit this draft to Moodle")
        print("    QUIT     — cancel without submitting")
        print("    (or type feedback to request a revision)\n")

        user_input = input("  Your response: ").strip()

        if not user_input:
            continue

        if user_input.upper() == "APPROVE":
            break

        if user_input.upper() in ("QUIT", "EXIT", "Q"):
            print("  Cancelled. Nothing was submitted.")
            return

        # Revision requested — regenerate with feedback appended
        _separator("Revising draft based on your feedback")
        print("  Calling Ollama... (this may take a minute)")

        revised_instructions = (
            f"{instructions}\n\n"
            f"IMPORTANT REVISION REQUEST FROM USER: {user_input}"
        )
        draft_resp = await generate_draft_from_instructions(
            title=title,
            instructions=revised_instructions,
            submission_type=sub_type,
            due_date=due_date,
        )
        draft_text = draft_resp.draft

    # ── Step 8: Submit ────────────────────────────────────────────
    _separator("Step 8: Submitting to Moodle")
    result = await perform_moodle_submission(assignment_id, draft_text)
    print(f"  Result: {result.get('msg', result)}")
    _separator("DONE")
