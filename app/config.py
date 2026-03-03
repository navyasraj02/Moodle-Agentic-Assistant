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

# ── LLM (Ollama) ──────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
# qwen2.5:1.5b ~1 GB – smallest model with tool/function calling support
# To override: set OLLAMA_MODEL=<model> in your .env file
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")  # 3b follows tools better than 1.5b
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.3"))  # lower = more deterministic

# ── FastAPI server (used by agent HTTP tools) ─────────────────
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")