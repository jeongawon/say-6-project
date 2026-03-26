"""Backward compatibility — re-exports from root thresholds.py (Single Source of Truth)."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from thresholds import *  # noqa: F401, F403, E402
