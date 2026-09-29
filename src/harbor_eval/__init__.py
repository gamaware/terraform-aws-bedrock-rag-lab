"""Offline evaluation, cost model and report data for the Harbor Goods policy assistant.

Nothing here calls AWS unless a command is given `--live`.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
