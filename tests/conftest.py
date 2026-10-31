"""Test configuration: an isolated SQLite file per test session and no background scheduler.

Set before any `app` module is imported so Settings picks the values up.
"""
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="twstock-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["NOTIFY_CONSOLE"] = "false"
