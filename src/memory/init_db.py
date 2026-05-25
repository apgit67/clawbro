"""
memory/init_db.py
-----------------
Re-exports init_db from the memory package for convenient direct import.

Usage:
    from memory.init_db import init_db
    init_db("~/.clawbro/memory.db")
"""
from memory import init_db  # noqa: F401
