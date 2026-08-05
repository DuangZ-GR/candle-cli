"""Cross-platform standard stream configuration for migration CLIs."""

from __future__ import annotations

import sys


def configure_utf8_stdio() -> None:
    """Make machine-readable CLI output UTF-8 even on Windows code pages."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="strict")
