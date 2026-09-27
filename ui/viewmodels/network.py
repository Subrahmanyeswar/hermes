# ui/viewmodels/network.py
"""Network and Provider Resilience ViewModels."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NetworkViewModel:
    connectivity: str = "UNKNOWN"
    circuit_state: str = "CLOSED"
    t1_provider: str = "nvidia_nim"
    t2_provider: str = "ollama"
    t3_provider: str = "ollama"
    t1_health: str = "HEALTHY"
    latency_ms_str: str = "N/A"
    ttft_ms_str: str = "N/A"
    reconnecting: bool = False
    retry_count: int = 0
