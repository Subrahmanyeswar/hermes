# ui/viewmodels/chat.py
"""Chat and Transcript ViewModels."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class ChatEntryKind(str, Enum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    SYSTEM_EVENT = "SYSTEM_EVENT"
    TOOL = "TOOL"
    VERIFICATION = "VERIFICATION"
    SECURITY = "SECURITY"
    SUBAGENT = "SUBAGENT"
    RECOVERY = "RECOVERY"
    CHECKPOINT = "CHECKPOINT"
    COMPACTION = "COMPACTION"


@dataclass(frozen=True)
class ChatMessageViewModel:
    message_id: str
    sequence: int
    timestamp_str: str
    kind: ChatEntryKind
    author_role: str
    content: str
    status: str = "DONE"
    tool_call_id: Optional[str] = None
    task_id: Optional[str] = None
    is_error: bool = False


@dataclass(frozen=True)
class ChatViewModel:
    messages: Tuple[ChatMessageViewModel, ...] = ()
    total_messages: int = 0
    is_streaming: bool = False
    streaming_partial_content: str = ""
    scroll_offset: int = 0
