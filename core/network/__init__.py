# core/network/__init__.py
"""
HERMES 2.x Network & Provider Resilience Layer
"""

from core.network.models import (
    DeadlineBudget,
    FailureClassification,
    LogicalRequest,
    ProviderCapabilities,
    ProviderType,
    RequestAttempt,
    RequestPhase,
    StreamDelta,
    is_retryable_failure,
)
from core.network.watchdog import StreamWatchdog
from core.network.retry import RetryPolicy
from core.network.health import ProviderHealthState, CircuitState, bounded_health_probe
from core.network.adapters import (
    BaseProviderAdapter,
    NvidiaAdapter,
    OllamaAdapter,
    FakeProviderAdapter,
    classify_httpx_exception,
)
from core.network.supervisor import NetworkSupervisor
from core.network.connectivity import (
    ConnectivityStatus,
    ConnectivityCondition,
    ProbeResult,
    ConnectivityStateSnapshot,
    ConnectivityMonitor,
    shared_connectivity_monitor,
)
from core.network.coordinator import (
    NetworkRecoveryCoordinator,
    shared_recovery_coordinator,
)

__all__ = [
    "DeadlineBudget",
    "FailureClassification",
    "LogicalRequest",
    "ProviderCapabilities",
    "ProviderType",
    "RequestAttempt",
    "RequestPhase",
    "StreamDelta",
    "is_retryable_failure",
    "StreamWatchdog",
    "RetryPolicy",
    "ProviderHealthState",
    "CircuitState",
    "bounded_health_probe",
    "BaseProviderAdapter",
    "NvidiaAdapter",
    "OllamaAdapter",
    "FakeProviderAdapter",
    "classify_httpx_exception",
    "NetworkSupervisor",
    "ConnectivityStatus",
    "ConnectivityCondition",
    "ProbeResult",
    "ConnectivityStateSnapshot",
    "ConnectivityMonitor",
    "shared_connectivity_monitor",
    "NetworkRecoveryCoordinator",
    "shared_recovery_coordinator",
]
