import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="sc-test-")
os.environ["SC_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["SC_STORAGE_DIR"] = f"{_tmp}/images"
os.environ["SC_QUEUE"] = "inline"
os.environ.pop("NAVER_CLIENT_ID", None)
os.environ.pop("NAVER_CLIENT_SECRET", None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
