"""
skills/fallback.py
------------------
Re-exports FallbackSkill from skills.base for convenient import.
The FallbackSkill implementation lives in skills/base.py to avoid
circular imports (base.py is imported by every skill).
"""
from skills.base import FallbackSkill  # noqa: F401
