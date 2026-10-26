import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("GOOGLE_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)
os.environ["AEGIS_FIRESTORE"] = "0"
# Tests use a fixed approval index so they don't depend on the live review state of dita-corpus.
os.environ["AEGIS_APPROVALS"] = str(ROOT / "tests" / "fixtures" / "approvals.json")
