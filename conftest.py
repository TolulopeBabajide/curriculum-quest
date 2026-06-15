"""Pytest bootstrap — make the project root importable so `import src...` works.

CI invokes the bare `pytest` console script (not `python -m pytest`), which does NOT add the project
root to `sys.path`. This roots the package import for every test, regardless of how pytest is invoked.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
