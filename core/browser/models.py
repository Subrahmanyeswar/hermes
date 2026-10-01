# core/browser/models.py
"""
Data models and representations for Browser Subsystem (Prompt 17).
Defines session configs, viewports, DOM elements, console logs,
network traces, and screenshot artifacts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Viewport:
    """Screen / browser viewport dimensions."""
    width: int = 1280
    height: int = 800
    device_scale_factor: float = 1.0
    is_mobile: bool = False

    @classmethod
    def desktop(cls) -> Viewport:
        return cls(width=1280, height=800, is_mobile=False)

    @classmethod
    def tablet(cls) -> Viewport:
        return cls(width=768, height=1024, is_mobile=False)

    @classmethod
    def mobile(cls) -> Viewport:
        return cls(width=375, height=667, device_scale_factor=2.0, is_mobile=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "device_scale_factor": self.device_scale_factor,
            "is_mobile": self.is_mobile,
        }


@dataclass
class BrowserSessionConfig:
    """Configuration for launching a browser session."""
    headless: bool = True
    viewport: Viewport = field(default_factory=Viewport.desktop)
    timeout: float = 30.0
    user_data_dir: Optional[str] = None
    browser_type: str = "edge_or_chrome"


@dataclass
class ConsoleMessage:
    """Represents a console log, warning, error, or exception emitted by the page."""
    msg_type: str  # log, info, warn, error, debug
    text: str
    location: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.msg_type,
            "text": self.text,
            "location": self.location,
            "timestamp": self.timestamp,
        }


@dataclass
class NetworkRequestRecord:
    """Network observation record with sensitive fields redacted."""
    request_id: str
    url: str
    method: str
    status: Optional[int] = None
    duration_seconds: float = 0.0
    resource_type: str = "other"
    request_headers: Dict[str, str] = field(default_factory=dict)
    response_headers: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "url": self.url,
            "method": self.method,
            "status": self.status,
            "duration": round(self.duration_seconds, 3),
            "resource_type": self.resource_type,
            "error": self.error,
            "timestamp": self.timestamp,
        }


@dataclass
class DOMElement:
    """Structured representation of an inspected DOM node."""
    tag_name: str
    text: str = ""
    attributes: Dict[str, str] = field(default_factory=dict)
    is_visible: bool = True
    is_interactive: bool = False
    role: Optional[str] = None
    children_count: int = 0

    @property
    def element_id(self) -> Optional[str]:
        return self.attributes.get("id")

    @property
    def classes(self) -> List[str]:
        c = self.attributes.get("class", "")
        return [cls.strip() for cls in c.split() if cls.strip()]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tag": self.tag_name,
            "text": self.text[:100] if self.text else "",
            "attributes": self.attributes,
            "is_visible": self.is_visible,
            "is_interactive": self.is_interactive,
            "role": self.role,
        }


@dataclass
class InspectResult:
    """Summary of structured DOM inspection."""
    url: str
    title: str
    elements: List[DOMElement] = field(default_factory=list)
    visible_text: str = ""
    interactive_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "element_count": len(self.elements),
            "interactive_count": self.interactive_count,
            "visible_text_preview": self.visible_text[:300],
            "elements": [e.to_dict() for e in self.elements[:50]],
        }


@dataclass
class ScreenshotArtifact:
    """Persisted screenshot metadata stored in CAS or artifacts store."""
    artifact_id: str
    sha256: str
    width: int
    height: int
    mime_type: str = "image/png"
    file_path: str = ""
    url: str = ""
    timestamp: float = field(default_factory=time.time)
    generation: int = 0

    @property
    def dimensions(self) -> str:
        return f"{self.width}x{self.height}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "sha256": self.sha256,
            "dimensions": f"{self.width}x{self.height}",
            "file_path": self.file_path,
            "url": self.url,
            "timestamp": self.timestamp,
            "generation": self.generation,
        }


@dataclass
class NavigationResult:
    """Result of a browser navigation action."""
    url: str
    status: int
    title: str
    duration_seconds: float
    success: bool
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "status": self.status,
            "title": self.title,
            "duration": round(self.duration_seconds, 3),
            "success": self.success,
            "error": self.error,
        }


@dataclass
class ActionResult:
    """Result of a semantic browser action (click, type, fill)."""
    action: str
    target: str
    success: bool
    duration_seconds: float
    error: Optional[str] = None
    before_state: Optional[str] = None
    after_state: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "target": self.target,
            "success": self.success,
            "duration": round(self.duration_seconds, 3),
            "error": self.error,
        }
