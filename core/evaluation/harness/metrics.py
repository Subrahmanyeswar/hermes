# core/evaluation/harness/metrics.py
"""
Evaluation Metrics & Infrastructure Noise Separation (Prompt 17).
Measures tool usage efficiency, separates infrastructure noise from model reasoning,
and accounts for token / evaluation costs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolMetricsTracker:
    """Tracks tool invocation counts and efficiency signals."""
    lsp_calls: int = 0
    browser_calls: int = 0
    test_calls: int = 0
    shell_calls: int = 0
    file_calls: int = 0
    failed_calls: int = 0
    redundant_calls: int = 0
    _last_calls: List[str] = field(default_factory=list)

    def record_call(self, tool_name: str, success: bool = True) -> None:
        name = tool_name.lower()
        if "lsp" in name:
            self.lsp_calls += 1
        elif "browser" in name:
            self.browser_calls += 1
        elif "test" in name or "pytest" in name:
            self.test_calls += 1
        elif "shell" in name or "bash" in name:
            self.shell_calls += 1
        elif "file" in name or "edit" in name or "write" in name:
            self.file_calls += 1

        if not success:
            self.failed_calls += 1

        # Check redundant sequential call
        if self._last_calls and self._last_calls[-1] == name:
            self.redundant_calls += 1
        self._last_calls.append(name)

    @property
    def total_calls(self) -> int:
        return self.lsp_calls + self.browser_calls + self.test_calls + self.shell_calls + self.file_calls

    def to_dict(self) -> Dict[str, int]:
        return {
            "total_calls": self.total_calls,
            "lsp_calls": self.lsp_calls,
            "browser_calls": self.browser_calls,
            "test_calls": self.test_calls,
            "shell_calls": self.shell_calls,
            "file_calls": self.file_calls,
            "failed_calls": self.failed_calls,
            "redundant_calls": self.redundant_calls,
        }


@dataclass
class LatencyNoiseTracker:
    """Separates infrastructure delays from core model reasoning time."""
    time_to_first_model: float = 0.0
    time_in_model: float = 0.0
    time_in_lsp: float = 0.0
    time_in_browser: float = 0.0
    time_in_tests: float = 0.0
    time_in_evaluator: float = 0.0
    time_total: float = 0.0
    agent_duration: float = 0.0
    infra_noise_duration: float = 0.0

    def record_step(self, step_name: str, duration: float, is_infra_noise: bool = False) -> None:
        """Record step duration separating infrastructure noise from agent reasoning."""
        if is_infra_noise:
            self.infra_noise_duration += duration
        else:
            self.agent_duration += duration
        self.time_total += duration

    def get_summary(self) -> Dict[str, float]:
        """Return noise separation summary."""
        total = self.agent_duration + self.infra_noise_duration
        ratio = (self.infra_noise_duration / total) if total > 0 else 0.0
        return {
            "agent_duration": round(self.agent_duration, 3),
            "infra_noise_duration": round(self.infra_noise_duration, 3),
            "infra_noise_ratio": round(ratio, 3),
            "total_duration": round(total, 3),
        }

    def to_dict(self) -> Dict[str, float]:
        return {
            "time_to_first_model": round(self.time_to_first_model, 3),
            "time_in_model": round(self.time_in_model, 3),
            "time_in_lsp": round(self.time_in_lsp, 3),
            "time_in_browser": round(self.time_in_browser, 3),
            "time_in_tests": round(self.time_in_tests, 3),
            "time_in_evaluator": round(self.time_in_evaluator, 3),
            "time_total": round(self.time_total, 3),
            "agent_duration": round(self.agent_duration, 3),
            "infra_noise_duration": round(self.infra_noise_duration, 3),
        }
