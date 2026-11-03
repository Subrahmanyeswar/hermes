"""
core/test_isolation.py
Hermes 2.x - Test Database Isolation and Disposable Fixtures (Section 17).

Ensures backend test executions never pollute, overwrite, or mutate demonstration
or active mission databases (e.g. campusflow.db, aurelion.db).
Uses HERMES_TEST_DB_PATH to redirect test operations to isolated temporary files.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

ENV_TEST_DB_VAR = "HERMES_TEST_DB_PATH"


def is_test_isolation_active() -> bool:
    """Returns True if test database isolation is currently active."""
    return ENV_TEST_DB_VAR in os.environ and bool(os.environ[ENV_TEST_DB_VAR])


def get_isolated_db_path(default_path: Path | str) -> Path:
    """
    Return the active isolated database path if HERMES_TEST_DB_PATH is set;
    otherwise return the canonical default path.
    """
    if is_test_isolation_active():
        return Path(os.environ[ENV_TEST_DB_VAR]).resolve()
    return Path(default_path).resolve()


@contextmanager
def isolated_test_database(seed_db_path: Optional[Path | str] = None) -> Generator[Path, None, None]:
    """
    Context manager that creates a temporary, disposable database file,
    sets HERMES_TEST_DB_PATH for child processes and in-process tests,
    and cleans up safely upon completion.
    """
    temp_dir = tempfile.mkdtemp(prefix="hermes_test_db_")
    disposable_db = Path(temp_dir) / "test_isolated.db"

    if seed_db_path:
        seed = Path(seed_db_path).resolve()
        if seed.exists() and seed.is_file():
            shutil.copy2(seed, disposable_db)
        else:
            disposable_db.touch()
    else:
        disposable_db.touch()

    old_val = os.environ.get(ENV_TEST_DB_VAR)
    os.environ[ENV_TEST_DB_VAR] = str(disposable_db)

    try:
        yield disposable_db
    finally:
        if old_val is not None:
            os.environ[ENV_TEST_DB_VAR] = old_val
        else:
            os.environ.pop(ENV_TEST_DB_VAR, None)

        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
