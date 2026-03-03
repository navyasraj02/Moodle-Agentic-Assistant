"""
Moodle Instructor Agent — scripted pipeline for creating assignments.

The pipeline orchestrates each step deterministically.
Human-in-the-loop: user supplies assignment details and must CONFIRM before
anything is written to Moodle.

Steps:
  1. Init instructor session
  2. Collect assignment title
  3. Collect assignment description
  4. Collect due date
  5. Review summary + confirmation loop (CONFIRM / edit)
  6. Create assignment in Moodle
"""

from __future__ import annotations

from datetime import datetime
from dateutil import parser as dtparser

from .instructor_playwright import ensure_instructor_session, create_assignment
from .config import COURSE_NAME


# ── UI helpers ─────────────────────────────────────────────────────

def _separator(title: str = "") -> None:
    print(f"\n{'='*60}")
    if title:
        print(f"  >> {title}")
        print("=" * 60)


def _prompt(label: str, default: str | None = None) -> str:
    """Prompt for a single required line.  Re-prompts on empty input."""
    suffix = f"  (default: {default})" if default else ""
    while True:
        val = input(f"  {label}{suffix}: ").strip()
        if val:
            return val
        if default is not None:
            return default
        print("    This field is required — please enter a value.")


def _prompt_multiline(label: str) -> str:
    """
    Collect a multi-line value.
    User types lines and presses Enter on a blank line to finish.
    """
    print(f"  {label}")
    print("  (Press Enter on a blank line when done)\n")
    lines: list[str] = []
    while True:
        line = input("  > ")
        if line.strip() == "":
            if lines:
                break
            print("    At least one line is required.")
            continue
        lines.append(line)
    return "\n".join(lines)


def _prompt_due_date() -> datetime:
    """Prompt for a due date string and parse it flexibly."""
    print("  Accepted formats:")
    print("    2026-03-20 23:59")
    print("    March 20 2026 11:59 PM")
    print("    20/3/2026 23:59")
    while True:
        raw = input("  Due date: ").strip()
        if not raw:
            print("    This field is required.")
            continue
        try:
            dt = dtparser.parse(raw, fuzzy=True)
            # If no time was given (midnight), default to end-of-day
            if dt.hour == 0 and dt.minute == 0 and ":" not in raw:
                dt = dt.replace(hour=23, minute=59)
            return dt
        except Exception:
            print("    Could not parse that date — please try again.")


# ── Pipeline ───────────────────────────────────────────────────────

async def run_instructor_loop() -> None:
    """
    Full instructor agent pipeline with human-in-the-loop input.
    """

    _separator("MOODLE INSTRUCTOR AGENT")
    print(f"  Course : {COURSE_NAME}")
    print("  Task   : Create a new assignment")

    # ── Step 1: Init session ──────────────────────────────────────
    _separator("Step 1: Initialising instructor session")
    await ensure_instructor_session()
    print("  Session ready.")

    # ── Step 2: Assignment title ──────────────────────────────────
    _separator("Step 2: Assignment title")
    title = _prompt("Title")

    # ── Step 3: Description ───────────────────────────────────────
    _separator("Step 3: Assignment description / instructions")
    description = _prompt_multiline("Enter the instructions students will see:")

    # ── Step 4: Due date ──────────────────────────────────────────
    _separator("Step 4: Due date")
    due_date = _prompt_due_date()

    if due_date < datetime.now():
        print(f"\n  NOTE: {due_date.strftime('%Y-%m-%d %H:%M')} is in the past.")
        print("  The assignment will be created but students cannot submit after the deadline.")

    # ── Step 5: Review + confirmation loop ───────────────────────
    while True:
        _separator("ASSIGNMENT SUMMARY — REVIEW BEFORE CREATING")
        print(f"  Title        : {title}")
        print(f"  Due date     : {due_date.strftime('%A, %d %B %Y, %I:%M %p')}")
        print(f"  Submission   : Online text only")
        print(f"  Course       : {COURSE_NAME}")
        print()
        # Preview description (first 200 chars)
        preview = description[:200] + ("..." if len(description) > 200 else "")
        print(f"  Description preview:\n    {preview}")
        print()
        print("  Options:")
        print("    CONFIRM — create this assignment in Moodle")
        print("    TITLE   — edit title")
        print("    DESC    — edit description")
        print("    DATE    — edit due date")
        print("    QUIT    — exit without creating")
        print()

        choice = input("  Your choice: ").strip().upper()

        if choice == "CONFIRM":
            break
        if choice in ("QUIT", "EXIT", "Q"):
            print("\n  Cancelled. Nothing was created.")
            return
        if choice == "TITLE":
            _separator("Edit title")
            title = _prompt("New title", default=title)
        elif choice == "DESC":
            _separator("Edit description")
            description = _prompt_multiline("Enter new description:")
        elif choice == "DATE":
            _separator("Edit due date")
            due_date = _prompt_due_date()
        else:
            print("    Unrecognised option — type CONFIRM, TITLE, DESC, DATE, or QUIT.")

    # ── Step 6: Create assignment ─────────────────────────────────
    _separator("Step 6: Creating assignment in Moodle")
    print("  Opening browser and submitting the form...")

    result = await create_assignment(
        title=title,
        description=description,
        due_date=due_date,
    )

    print(f"\n  Result  : {result.get('msg', result)}")
    if result.get("screenshot"):
        print(f"  Screenshot saved → {result['screenshot']}")

    _separator("DONE")
