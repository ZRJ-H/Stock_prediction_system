"""
Local configuration loader.

Loads simple KEY=VALUE entries from a project-local .env file without adding a
third-party dependency. Existing environment variables always win.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_local_env(env_path: str | Path = ".env") -> None:
    """Load environment variables from a local .env file if it exists.

    Supported syntax:
      - KEY=VALUE
      - comments starting with #
      - optional single/double quotes around VALUE
    """
    path = Path(env_path)
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ[key] = value
