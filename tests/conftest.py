import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="archex-test-")
os.environ["ARCHEX_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["ARCHEX_MODEL_DIR"] = f"{_tmp}/models"
