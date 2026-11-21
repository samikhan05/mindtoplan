"""Settings. Model access comes only from .env; nothing here is a fact from a message pack."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env", override=True)   # .env wins: editors (e.g. VS Code) may pre-load it into the
                                             # terminal without expanding ${VAR}, leaving a literal key

BASE_URL = os.getenv("BASE_URL", "").strip()
MODEL_NAME = os.getenv("MODEL_NAME", "").strip()
API_KEY = os.getenv("API_KEY", "").strip()
REASONING_EFFORT = os.getenv("REASONING_EFFORT", "").strip()   # optional, for thinking models (e.g. low)
EXTRACTION_MODE = os.getenv("EXTRACTION_MODE", "generic").strip() or "generic"   # experiment: "fixed"
# Optional backup route, used only when the primary answers "overloaded" (429/5xx): same task, other provider
FALLBACK_BASE_URL = os.getenv("FALLBACK_BASE_URL", "").strip()
FALLBACK_MODEL_NAME = os.getenv("FALLBACK_MODEL_NAME", "").strip()
FALLBACK_API_KEY = os.getenv("FALLBACK_API_KEY", "").strip()
ALLOWED_MODELS =[m.strip() for m in os.getenv("ALLOWED_MODELS", "").split(",") if m.strip()]

STATE_DIR = ROOT / ".state"
OUT_DIR = ROOT / "out"

# Hard limits from the rules
FULL_RUN_SECONDS = 120
UPDATE_SECONDS = 60
UPDATE_MAX_CALLS = 5
SAFETY_SECONDS = 5          # stop this long before the limit so we exit cleanly
FULL_RUN_MAX_CALLS = 8      # our own cap for a full run: 1 reading + rule escape hatches + retries

# Generic sender authority (higher may override lower on the same entity+attribute)
AUTHORITY = {"institution": 4, "finance": 4, "organizer": 3, "vendor": 2,
             "student": 1, "individual": 0, "unknown": 0}

# Generic planning conventions used only when the pack is silent (shown in the plan as assumptions)
DEFAULT_MINUTES = {"opening": 10, "meal": 30, "closing": 15}
MIN_HACKING_MINUTES = 30
