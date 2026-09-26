# core/context/__init__.py
"""
HERMES 2.x Context Engine.
Provides model-agnostic, state-aware, cache-aware context management,
tiered compaction, externalized output storage, and high-signal prompt assembly.
"""

from core.context.models import (
    ContextSectionType,
    ContextSourceType,
    ContextFreshness,
    ContextPriority,
    ContextProvenance,
    ContextItem,
    ContextVersion,
    ActiveFileSnippet,
)
from core.context.budget import (
    BudgetHealthState,
    ContextCapacity,
    TokenEstimator,
    ContextBudgetReport,
    ContextBudgeter,
)
from core.context.external_store import (
    RetentionPolicy,
    ExternalizedArtifact,
    ExternalizedOutputStore,
    externalized_output_store,
)
from core.context.tool_results import (
    ToolResultClearState,
    ToolResultRecord,
    ToolResultStore,
    tool_result_store,
)
from core.context.freshness import (
    FreshnessChecker,
    freshness_checker,
)
from core.context.relevance import (
    RelevanceEngine,
    relevance_engine,
)
from core.context.compactor import (
    CompactionSummary,
    Compactor,
)
from core.context.cache_builder import (
    CacheSegmentType,
    CachePolicy,
    CacheCapabilities,
    CacheSegment,
    CacheMetrics,
    CacheAwarePromptBuilder,
)
from core.context.serializer import (
    ContextSerializer,
    context_serializer,
)
from core.context.validation import (
    ValidationIssue,
    ValidationResult,
    ContextPackValidator,
    context_validator,
)
from core.context.pack import (
    ContextPack,
)
from core.context.engine import (
    ContextEngine,
    context_engine,
)

__all__ = [
    "ContextSectionType",
    "ContextSourceType",
    "ContextFreshness",
    "ContextPriority",
    "ContextProvenance",
    "ContextItem",
    "ContextVersion",
    "ActiveFileSnippet",
    "BudgetHealthState",
    "ContextCapacity",
    "TokenEstimator",
    "ContextBudgetReport",
    "ContextBudgeter",
    "RetentionPolicy",
    "ExternalizedArtifact",
    "ExternalizedOutputStore",
    "externalized_output_store",
    "ToolResultClearState",
    "ToolResultRecord",
    "ToolResultStore",
    "tool_result_store",
    "FreshnessChecker",
    "freshness_checker",
    "RelevanceEngine",
    "relevance_engine",
    "CompactionSummary",
    "Compactor",
    "CacheSegmentType",
    "CachePolicy",
    "CacheCapabilities",
    "CacheSegment",
    "CacheMetrics",
    "CacheAwarePromptBuilder",
    "ContextSerializer",
    "context_serializer",
    "ValidationIssue",
    "ValidationResult",
    "ContextPackValidator",
    "context_validator",
    "ContextPack",
    "ContextEngine",
    "context_engine",
]
