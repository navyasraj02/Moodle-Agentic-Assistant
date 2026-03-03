#!/usr/bin/env python
"""
CLI entry-point: launches the Moodle Student Agent loop.

Usage:
    python run_agent.py
    python run_agent.py "Custom task description"
"""

import sys
import asyncio

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def main():
    # Import here to ensure event loop policy is set first
    from app.agents import run_agent_loop
    
    task = sys.argv[1] if len(sys.argv) > 1 else None
    
    try:
        asyncio.run(run_agent_loop(task))
    except KeyboardInterrupt:
        print("\n[system] Interrupted by user.")


if __name__ == "__main__":
    main()
