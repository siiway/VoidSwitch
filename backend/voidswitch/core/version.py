"""Runtime build/version metadata."""

from __future__ import annotations

import os
import subprocess
from functools import cache


@cache
def commit_id() -> str | None:
    for key in ("VOIDSWITCH_COMMIT", "GIT_COMMIT", "COMMIT_SHA", "SOURCE_VERSION"):
        value = os.environ.get(key)
        if value:
            return value[:12]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=1,
        )
        return result.stdout.strip() or None
    except Exception:
        return None
