# ui/viewmodels/memory.py
"""
Memory ViewModels.

STRICT INVARIANT:
The renderer and viewmodel NEVER read MEMORY.md or touch the filesystem.
All memory facts are supplied strictly through in-memory state projections.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class MemoryViewModel:
    project: str = "default"
    facts: Tuple[str, ...] = ()
    total_facts: int = 0
    is_empty: bool = True
