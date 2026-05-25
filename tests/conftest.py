"""
conftest.py — shared pytest fixtures for ClawBro integration tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure src/ is on sys.path for all tests
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
