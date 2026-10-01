# core/browser/__init__.py
"""
Browser Automation & Environment Awareness Subsystem for HERMES 2.x (Prompt 17).
"""

from core.browser.models import (
    ActionResult,
    BrowserSessionConfig,
    ConsoleMessage,
    DOMElement,
    InspectResult,
    NavigationResult,
    NetworkRequestRecord,
    ScreenshotArtifact,
    Viewport,
)
from core.browser.security import (
    BrowserSecurityManager,
    BrowserSecurityViolation,
)
from core.browser.driver import (
    BrowserDriver,
    CdpBrowserDriver,
    SimulatedBrowserDriver,
)
from core.browser.dev_server import (
    DevServerInfo,
    DevServerManager,
)
from core.browser.manager import BrowserManager
from core.browser.tools import (
    BrowserClickTool,
    BrowserConsoleTool,
    BrowserInspectTool,
    BrowserNavigateTool,
    BrowserNetworkTool,
    BrowserScreenshotTool,
    BrowserTypeTool,
)

__all__ = [
    "ActionResult",
    "BrowserSessionConfig",
    "ConsoleMessage",
    "DOMElement",
    "InspectResult",
    "NavigationResult",
    "NetworkRequestRecord",
    "ScreenshotArtifact",
    "Viewport",
    "BrowserSecurityManager",
    "BrowserSecurityViolation",
    "BrowserDriver",
    "CdpBrowserDriver",
    "SimulatedBrowserDriver",
    "DevServerInfo",
    "DevServerManager",
    "BrowserManager",
    "BrowserClickTool",
    "BrowserConsoleTool",
    "BrowserInspectTool",
    "BrowserNavigateTool",
    "BrowserNetworkTool",
    "BrowserScreenshotTool",
    "BrowserTypeTool",
]
