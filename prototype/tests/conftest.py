import os
import sys
from pathlib import Path

os.environ.setdefault("SC_DB_PATH", ":memory:")
os.environ.setdefault("SC_FIXTURE_DELAY", "0")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
