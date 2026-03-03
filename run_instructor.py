#!/usr/bin/env python
"""
CLI entry-point: launches the Moodle Instructor Agent loop.

Usage:
    python run_instructor.py
"""

import sys
import asyncio

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def main():
    # Import after event-loop policy is set
    from app.instructor_agent import run_instructor_loop

    try:
        asyncio.run(run_instructor_loop())
    except KeyboardInterrupt:
        print("\n[system] Interrupted by user.")


if __name__ == "__main__":
    main()
