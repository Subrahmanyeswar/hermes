# tools/platform/__init__.py
"""
HERMES 2.x Claude-Code-Class Tool Platform & Execution Engine.
Public interface exporting canonical tool platform components.
"""

from tools.platform.specs import (
    RiskLevel,
    ToolAvailability,
    ResponseFormat,
    RiskMetadata,
    ToolExample,
    ToolSchema,
    ToolSpec,
)
from tools.platform.errors import (
    ToolErrorCode,
    ToolError,
    ErrorGuidance,
)
from tools.platform.output import (
    ShapedOutput,
    OutputRecord,
    OutputStore,
    OutputShaper,
    output_store,
)
from tools.platform.retry import (
    RetryDecision,
    RetryEvaluation,
    RetryPolicy,
)
from tools.platform.permissions import (
    PermissionDecision,
    PermissionPolicy,
)
from tools.platform.validator import (
    Validator,
)
from tools.platform.core_tools import (
    FSReadTool,
    FSEditTool,
    FSWriteTool,
    ShellBashTool,
    SearchGlobTool,
    SearchGrepTool,
    TaskTodoTool,
    TaskDelegateTool,
    UserAskTool,
)
from tools.platform.catalog import (
    ToolCatalog,
    tool_catalog,
)
from tools.platform.search import (
    ToolSearchResult,
    ToolSearch,
    tool_search,
)
from tools.platform.executor import (
    ToolPlatformResult,
    ToolExecutor,
)
from tools.platform.batch import (
    BatchToolRequest,
    BatchExecutionResult,
    ToolBatchExecutor,
)
from tools.platform.linter import (
    LintReport,
    ToolSpecLinter,
)
from tools.platform.file_identity import (
    FileIdentity,
    FileIdentityCache,
    file_identity_cache,
)
from tools.platform.workspace_discovery import (
    WorkspaceProfile,
    WorkspaceDiscoveryService,
    workspace_discovery,
)
from tools.platform.evaluation import (
    ToolEvaluationTask,
    ToolEvaluationReport,
    ToolEvaluationSuite,
)


__all__ = [
    # Specs
    "RiskLevel",
    "ToolAvailability",
    "ResponseFormat",
    "RiskMetadata",
    "ToolExample",
    "ToolSchema",
    "ToolSpec",
    # Errors
    "ToolErrorCode",
    "ToolError",
    "ErrorGuidance",
    # Output
    "ShapedOutput",
    "OutputRecord",
    "OutputStore",
    "OutputShaper",
    "output_store",
    # Retry
    "RetryDecision",
    "RetryEvaluation",
    "RetryPolicy",
    # Permissions
    "PermissionDecision",
    "PermissionPolicy",
    # Validator
    "Validator",
    # Core Tools
    "FSReadTool",
    "FSEditTool",
    "FSWriteTool",
    "ShellBashTool",
    "SearchGlobTool",
    "SearchGrepTool",
    "TaskTodoTool",
    "TaskDelegateTool",
    "UserAskTool",
    # Catalog
    "ToolCatalog",
    "tool_catalog",
    # Search
    "ToolSearchResult",
    "ToolSearch",
    "tool_search",
    # Executor
    "ToolPlatformResult",
    "ToolExecutor",
    # Batch
    "BatchToolRequest",
    "BatchExecutionResult",
    "ToolBatchExecutor",
    # Linter & Eval
    "LintReport",
    "ToolSpecLinter",
    "ToolEvaluationTask",
    "ToolEvaluationReport",
    "ToolEvaluationSuite",
    # File Identity & Discovery (Prompt 6)
    "FileIdentity",
    "FileIdentityCache",
    "file_identity_cache",
    "WorkspaceProfile",
    "WorkspaceDiscoveryService",
    "workspace_discovery",
]

