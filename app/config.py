import os
from dotenv import load_dotenv

load_dotenv()

def _bool(v: str, default: bool = False) -> bool:
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")

MOODLE_URL = os.getenv("MOODLE_URL", "http://127.0.0.1:8080")

STUDENT_USERNAME = os.getenv("STUDENT_USERNAME", "")
STUDENT_PASSWORD = os.getenv("STUDENT_PASSWORD", "")

INSTRUCTOR_USERNAME = os.getenv("INSTRUCTOR_USERNAME", "")
INSTRUCTOR_PASSWORD = os.getenv("INSTRUCTOR_PASSWORD", "")

COURSE_NAME = os.getenv("COURSE_NAME", "AGENT101")

HEADLESS = _bool(os.getenv("HEADLESS"), default=False)
BROWSER = os.getenv("BROWSER", "chromium")
TIMEOUT_MS = int(os.getenv("TIMEOUT_MS", "30000"))

SESSION_DIR = os.path.join(os.getcwd(), "sessions")
SCREENSHOT_DIR = os.path.join(os.getcwd(), "screenshots")
STORAGE_STATE_PATH = os.path.join(SESSION_DIR, "storage_state.json")

os.makedirs(SESSION_DIR, exist_ok=True)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)