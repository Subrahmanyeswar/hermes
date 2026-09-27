# ui/viewmodels/checkpoint.py
"""Checkpoint Selector ViewModels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class CheckpointItemViewModel:
    checkpoint_id: str
    sequence: int
    reason: str
    timestamp_str: str
    files_count: int = 0
    git_head: str = ""
    is_current: bool = False


@dataclass(frozen=True)
class CheckpointSelectorViewModel:
    checkpoints: Tuple[CheckpointItemViewModel, ...] = ()
    selected_index: int = 0
    visible: bool = False
