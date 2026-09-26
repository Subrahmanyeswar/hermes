# tools/platform/catalog.py
"""
Authoritative Tool Catalog for HERMES 2.x Tool Platform.
Evolves the existing tool registry into a canonical metadata catalog
with semantic namespaces, aliases, progressive discovery, and backward compatibility.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Set, Type

from tools.base import BaseTool
from tools.registry import (
    _REGISTRY,
    TOOL_ALIASES as LEGACY_ALIASES,
    _ensure_tools_loaded,
)
from tools.platform.specs import (
    ToolSpec,
    ToolSchema,
    ToolExample,
    RiskMetadata,
    RiskLevel,
    ToolAvailability,
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


class ToolCatalog:
    """
    Metadata-oriented registry and resolver for all agent-facing tools.
    """

    def __init__(self) -> None:
        self._specs: Dict[str, ToolSpec] = {}
        self._aliases: Dict[str, str] = {}
        self._lock = threading.Lock()
        self._initialized: bool = False

    def initialize(self) -> None:
        """Register core tools and bridge all existing tools from tools.registry."""
        with self._lock:
            if self._initialized:
                return

            _ensure_tools_loaded()

            # ── 1. Register Canonical Core Tools ─────────────────────────────
            self._register_core_tools()

            # ── 2. Bridge Legacy Registry Tools ──────────────────────────────
            self._bridge_legacy_registry()

            # ── 3. Establish Canonical Aliases ───────────────────────────────
            self._register_aliases()

            self._initialized = True

    def register(self, spec: ToolSpec) -> None:
        """Register a canonical ToolSpec."""
        with self._lock:
            self._specs[spec.canonical_name] = spec
            for alias in spec.aliases:
                self._aliases[alias] = spec.canonical_name

    def resolve_name(self, name: str) -> str:
        """Resolve any tool name or alias to its canonical name."""
        if not self._initialized:
            self.initialize()
        return self._aliases.get(name, name)

    def get(self, name: str) -> Optional[ToolSpec]:
        """Retrieve a ToolSpec by canonical name or alias."""
        if not self._initialized:
            self.initialize()
        canon = self.resolve_name(name)
        return self._specs.get(canon)

    def list_core(self) -> List[ToolSpec]:
        """Return the 9 canonical, always-available core tools."""
        if not self._initialized:
            self.initialize()
        return [s for s in self._specs.values() if s.is_core and s.availability == ToolAvailability.AVAILABLE]

    def list_all(self) -> List[ToolSpec]:
        """Return all registered tool specifications."""
        if not self._initialized:
            self.initialize()
        return sorted(self._specs.values(), key=lambda s: s.canonical_name)

    def list_available(self) -> List[ToolSpec]:
        """Return all available, non-disabled tools."""
        if not self._initialized:
            self.initialize()
        return [s for s in self._specs.values() if s.availability == ToolAvailability.AVAILABLE]

    def list_tools(self) -> List[ToolSpec]:
        """Return all registered tool specifications."""
        return self.list_all()

    def get_core_tools(self) -> List[ToolSpec]:
        """Return the core tool specifications."""
        return self.list_core()

    def get_openai_tools(self, core_only: bool = True) -> List[Dict[str, Any]]:
        """Return OpenAI / NIM function tool definitions."""
        specs = self.list_core() if core_only else self.list_available()
        return [s.schema.to_openai_dict() for s in specs]

    def get_ollama_tools(self, core_only: bool = True) -> List[Dict[str, Any]]:
        """Return Ollama function tool definitions."""
        specs = self.list_core() if core_only else self.list_available()
        return [s.schema.to_ollama_dict() for s in specs]

    def export_catalog(self) -> Dict[str, Any]:
        """Export the full catalog as a serializable dict."""
        if not self._initialized:
            self.initialize()
        return {
            "version": "2.0",
            "total_tools": len(self._specs),
            "core_tools_count": len(self.list_core()),
            "tools": {name: spec.to_dict() for name, spec in sorted(self._specs.items())},
            "aliases": dict(sorted(self._aliases.items())),
        }

    # ── Private Registration Helpers ─────────────────────────────────────────

    def _register_core_tools(self) -> None:
        """Register the 9 foundational HERMES core tools."""

        # 1. fs.read
        self._specs["fs.read"] = ToolSpec(
            canonical_name="fs.read",
            display_name="Read File",
            description="Read file contents or specific line ranges from disk with 1-based line numbering. Use when inspecting, viewing, or reviewing source files (e.g. start_line=10, end_line=50 or offset/limit).",
            category="fs",
            version="2.0",
            schema=ToolSchema(
                name="fs.read",
                description="Read file contents or specific line ranges within workspace with line numbers.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path to file"},
                        "start_line": {"type": "integer", "description": "1-based starting line (inclusive)"},
                        "offset": {"type": "integer", "description": "Alias for start_line (1-based)"},
                        "end_line": {"type": "integer", "description": "1-based ending line (inclusive)"},
                        "max_lines": {"type": "integer", "description": "Maximum lines to return"},
                        "limit": {"type": "integer", "description": "Alias for max_lines"},
                        "encoding": {"type": "string", "default": "utf-8"},
                        "response_format": {"type": "string", "enum": ["concise", "normal", "detailed"], "default": "normal"},
                    },
                    "required": ["path"],
                },
                required=["path"],
            ),
            risk=RiskMetadata(risk_score=0.1, risk_level=RiskLevel.READ_ONLY, idempotent=True),
            implementation_cls=FSReadTool,
            examples=[
                ToolExample(
                    intent="Read lines 200 to 260 of auth.py",
                    input={"path": "src/auth.py", "start_line": 200, "end_line": 260},
                    expected_output_summary="File: src/auth.py\nLines: 200-260 of 450\n 200 | def authenticate...",
                ),
                ToolExample(
                    intent="Attempting to read outside workspace fails",
                    input={"path": "../../etc/passwd"},
                    is_failure_example=True,
                    failure_reason="Path traversal prohibited",
                ),
            ],
            aliases=["read_file", "read", "view_file"],
            batch_safe=True,
            tags=["fs", "read", "file", "view", "inspect"],
        )

        # 2. fs.edit
        self._specs["fs.edit"] = ToolSpec(
            canonical_name="fs.edit",
            display_name="Edit File",
            description="Apply an exact surgical text replacement to an existing file. By default expected_occurrences=1. Fails if target text is absent or ambiguous.",
            category="fs",
            version="2.0",
            schema=ToolSchema(
                name="fs.edit",
                description="Replace exact old_string with new_string in an existing file.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path to file"},
                        "old_string": {"type": "string", "description": "Exact text to replace (no fuzzy matching)"},
                        "old_text": {"type": "string", "description": "Alias for old_string"},
                        "new_string": {"type": "string", "description": "Replacement text"},
                        "new_text": {"type": "string", "description": "Alias for new_string"},
                        "expected_occurrences": {"type": "integer", "default": 1, "description": "Expected match count (default: 1)"},
                        "replace_all": {"type": "boolean", "default": False, "description": "Replace all occurrences if True"},
                        "allow_large_diff": {"type": "boolean", "default": False, "description": "Permit large diffs exceeding safety limits"},
                        "response_format": {"type": "string", "enum": ["concise", "normal", "detailed"], "default": "normal"},
                    },
                    "required": ["path"],
                },
                required=["path"],
            ),
            risk=RiskMetadata(risk_score=0.3, risk_level=RiskLevel.LOW, writes_files=True, affects_workspace=True, blocked_in=["plan"], idempotent=False),
            implementation_cls=FSEditTool,
            examples=[
                ToolExample(
                    intent="Replace timeout value uniquely in config.py",
                    input={"path": "config.py", "old_string": "timeout = 30", "new_string": "timeout = 60"},
                    expected_output_summary="Successfully edited 'config.py'. Replaced 1 occurrence(s) (+1/-1 lines).",
                ),
                ToolExample(
                    intent="Fails safely when old_string appears multiple times without qualification",
                    input={"path": "config.py", "old_string": "port = 8080", "new_string": "port = 9000"},
                    is_failure_example=True,
                    failure_reason="EDIT_TARGET_NOT_UNIQUE: old_string matched 3 times. Refine old_string with unique surrounding context.",
                ),
            ],
            aliases=["edit", "edit_file", "replace_file_content"],
            batch_safe=False,
            tags=["fs", "edit", "replace", "modify", "surgical"],
        )

        # 3. fs.write
        self._specs["fs.write"] = ToolSpec(
            canonical_name="fs.write",
            display_name="Write File",
            description="Create a new file or completely overwrite an existing file atomically. Use fs.edit for surgical modifications.",
            category="fs",
            version="2.0",
            schema=ToolSchema(
                name="fs.write",
                description="Create or overwrite a file with given text content.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path to file"},
                        "content": {"type": "string", "description": "Content to write"},
                        "create_parents": {"type": "boolean", "default": True},
                        "allow_overwrite": {"type": "boolean", "default": True, "description": "Allow overwriting existing file"},
                        "response_format": {"type": "string", "enum": ["concise", "normal", "detailed"], "default": "normal"},
                    },
                    "required": ["path", "content"],
                },
                required=["path", "content"],
            ),
            risk=RiskMetadata(risk_score=0.4, risk_level=RiskLevel.MEDIUM, writes_files=True, affects_workspace=True, blocked_in=["plan"], idempotent=False),
            implementation_cls=FSWriteTool,
            examples=[
                ToolExample(
                    intent="Create a new config file",
                    input={"path": "config.json", "content": "{\n  \"env\": \"dev\"\n}\n"},
                    expected_output_summary="Successfully wrote 24 bytes (3 lines) to 'config.json'.",
                )
            ],
            aliases=["write_file", "write"],
            batch_safe=False,
            tags=["fs", "write", "create", "file"],
        )

        # 4. shell.bash
        self._specs["shell.bash"] = ToolSpec(
            canonical_name="shell.bash",
            display_name="Bash Shell",
            description="Execute shell commands under strict security gates and timeouts.",
            category="shell",
            version="1.0",
            schema=ToolSchema(
                name="shell.bash",
                description="Execute a shell command with security validation.",
                parameters={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Shell command to run"},
                        "working_dir": {"type": "string", "default": "."},
                        "timeout_seconds": {"type": "integer", "default": 60},
                        "response_format": {"type": "string", "enum": ["concise", "normal", "detailed"], "default": "normal"},
                    },
                    "required": ["command"],
                },
                required=["command"],
            ),
            risk=RiskMetadata(
                risk_score=0.7,
                risk_level=RiskLevel.HIGH,
                executes_commands=True,
                affects_workspace=True,
                idempotent=False,
                blocked_in=["safe", "plan"],
            ),
            implementation_cls=ShellBashTool,
            examples=[
                ToolExample(
                    intent="Run pytest",
                    input={"command": "pytest tests/ -v"},
                    expected_output_summary="Pytest execution output",
                )
            ],
            aliases=["bash_exec", "bash", "shell"],
            batch_safe=False,
            tags=["shell", "bash", "command", "exec", "terminal"],
        )

        # 5. search.glob
        self._specs["search.glob"] = ToolSpec(
            canonical_name="search.glob",
            display_name="Glob File Search",
            description="Find files matching a glob pattern relative to workspace root (e.g. '**/*.py'). Ignores noise dirs (.git, node_modules, .venv).",
            category="search",
            version="2.0",
            schema=ToolSchema(
                name="search.glob",
                description="Find matching files using glob patterns.",
                parameters={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Glob pattern (e.g. '**/*.py', 'src/**/*.ts')"},
                        "base_path": {"type": "string", "default": "."},
                        "max_results": {"type": "integer", "default": 50},
                        "include_directories": {"type": "boolean", "default": False},
                        "response_format": {"type": "string", "enum": ["concise", "normal", "detailed"], "default": "normal"},
                    },
                    "required": ["pattern"],
                },
                required=["pattern"],
            ),
            risk=RiskMetadata(risk_score=0.1, risk_level=RiskLevel.READ_ONLY, idempotent=True),
            implementation_cls=SearchGlobTool,
            examples=[
                ToolExample(
                    intent="Find all Python files under src",
                    input={"pattern": "src/**/*.py"},
                    expected_output_summary="Matched 12 file(s) for pattern 'src/**/*.py':",
                )
            ],
            aliases=["glob", "list_directory", "list_dir"],
            batch_safe=True,
            tags=["search", "glob", "files", "find", "structure"],
        )

        # 6. search.grep
        self._specs["search.grep"] = ToolSpec(
            canonical_name="search.grep",
            display_name="Grep Content Search",
            description="Search file contents for regex or literal text patterns with line numbers and context. Line-addressable output (file:line: match).",
            category="search",
            version="2.0",
            schema=ToolSchema(
                name="search.grep",
                description="Search file contents for regex/text patterns with context.",
                parameters={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Regex or text pattern to search for"},
                        "path": {"type": "string", "default": "."},
                        "file_pattern": {"type": "string", "description": "Optional file filter (e.g. '*.py')"},
                        "max_results": {"type": "integer", "default": 50},
                        "context_lines": {"type": "integer", "default": 1},
                        "case_sensitive": {"type": "boolean", "default": False},
                        "literal": {"type": "boolean", "default": False, "description": "Treat pattern as literal string"},
                        "response_format": {"type": "string", "enum": ["concise", "normal", "detailed"], "default": "normal"},
                    },
                    "required": ["pattern"],
                },
                required=["pattern"],
            ),
            risk=RiskMetadata(risk_score=0.1, risk_level=RiskLevel.READ_ONLY, idempotent=True),
            implementation_cls=SearchGrepTool,
            examples=[
                ToolExample(
                    intent="Find all EventBus.publish occurrences",
                    input={"pattern": "EventBus.publish", "path": "src/"},
                    expected_output_summary="Found 7 match(es) for pattern 'EventBus.publish':\nsrc/core/loop.py:142:\n  142: EventBus.publish(...)",
                )
            ],
            aliases=["grep", "search_files"],
            batch_safe=True,
            tags=["search", "grep", "regex", "content", "code", "symbol", "find", "definition", "string", "text"],
        )


        # 7. task.todo
        self._specs["task.todo"] = ToolSpec(
            canonical_name="task.todo",
            display_name="Task Todo List",
            description="Manage planned checklist objectives without altering authoritative state.",
            category="task",
            version="1.0",
            schema=ToolSchema(
                name="task.todo",
                description="Manage visible checklist items (add, update, complete, remove, list).",
                parameters={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["add", "update", "complete", "remove", "list"]},
                        "item_id": {"type": "string"},
                        "title": {"type": "string"},
                        "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                    },
                    "required": ["action"],
                },
                required=["action"],
            ),
            risk=RiskMetadata(risk_score=0.1, risk_level=RiskLevel.READ_ONLY, idempotent=True),
            implementation_cls=TaskTodoTool,
            examples=[
                ToolExample(
                    intent="Add objective to checklist",
                    input={"action": "add", "title": "Run migrations"},
                    expected_output_summary="Added todo item",
                )
            ],
            aliases=["todo"],
            tags=["task", "todo", "checklist", "planning", "track"],
        )

        # 8. task.delegate
        self._specs["task.delegate"] = ToolSpec(
            canonical_name="task.delegate",
            display_name="Task Delegate",
            description="Delegation contract to specialized subagents (deferred to Prompt 10).",
            category="task",
            version="1.0",
            schema=ToolSchema(
                name="task.delegate",
                description="Request subagent delegation for an isolated objective.",
                parameters={
                    "type": "object",
                    "properties": {
                        "target_role": {"type": "string"},
                        "objective": {"type": "string"},
                        "context_files": {"type": "array", "items": {"type": "string"}},
                        "constraints": {"type": "string"},
                    },
                    "required": ["target_role", "objective"],
                },
                required=["target_role", "objective"],
            ),
            risk=RiskMetadata(risk_score=0.2, risk_level=RiskLevel.LOW),
            implementation_cls=TaskDelegateTool,
            examples=[
                ToolExample(
                    intent="Request delegation to researcher",
                    input={"target_role": "researcher", "objective": "Investigate security issue"},
                    expected_output_summary="Delegation response",
                )
            ],
            aliases=["delegate"],
            tags=["task", "delegate", "subagent"],
        )

        # 9. user.ask
        self._specs["user.ask"] = ToolSpec(
            canonical_name="user.ask",
            display_name="Ask User",
            description="Ask the user a clarifying question when requirements are ambiguous.",
            category="user",
            version="1.0",
            schema=ToolSchema(
                name="user.ask",
                description="Prompt the user with a question or choices.",
                parameters={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "context": {"type": "string"},
                        "choices": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["question"],
                },
                required=["question"],
            ),
            risk=RiskMetadata(risk_score=0.1, risk_level=RiskLevel.READ_ONLY),
            implementation_cls=UserAskTool,
            examples=[
                ToolExample(
                    intent="Ask user to clarify database preference",
                    input={"question": "Use Postgres or SQLite?", "choices": ["postgres", "sqlite"]},
                    expected_output_summary="User question prompted",
                )
            ],
            aliases=["ask_user", "ask"],
            tags=["user", "ask", "clarify", "question", "prompt"],
        )

    def _bridge_legacy_registry(self) -> None:
        """Import all legacy tools from tools.registry._REGISTRY and wrap them in ToolSpecs."""
        legacy_core_aliases = {
            "read_file", "write_file", "bash_exec", "list_directory", "list_dir",
            "search_files", "grep", "read", "write", "edit"
        }
        for name, cls in _REGISTRY.items():
            if name in self._specs or name in legacy_core_aliases:
                continue

            # Determine category namespace from name
            if name.startswith("git_"):
                cat = "git"
            elif name in ("read_memory", "save_memory"):
                cat = "memory"
            elif name in ("web_fetch", "web_search"):
                cat = "network"
            elif name in ("run_python", "run_tests"):
                cat = "shell"
            elif name == "screenshot_to_code":
                cat = "vision"
            elif name.endswith("_file") or name.endswith("_folder"):
                cat = "fs"
            else:
                cat = "system"

            risk_s = getattr(cls, "risk_score", 0.3)
            r_level = (
                RiskLevel.READ_ONLY if risk_s <= 0.1
                else RiskLevel.LOW if risk_s <= 0.3
                else RiskLevel.MEDIUM if risk_s <= 0.5
                else RiskLevel.HIGH if risk_s <= 0.8
                else RiskLevel.CRITICAL
            )

            # Build schema from Input model if available
            inp_cls = getattr(cls, "Input", getattr(cls, "input_model", None))
            if inp_cls is not None:
                schema_fn = getattr(inp_cls, "model_json_schema", getattr(inp_cls, "schema", None))
                raw_schema = schema_fn() if schema_fn else {}
                params = {
                    "type": "object",
                    "properties": raw_schema.get("properties", {}),
                    "required": raw_schema.get("required", []),
                }
                req = raw_schema.get("required", [])
            else:
                params = {"type": "object", "properties": {}}
                req = []

            spec = ToolSpec(
                canonical_name=name,
                display_name=name.replace("_", " ").title(),
                description=getattr(cls, "description", name),
                category=cat,
                version="1.0",
                schema=ToolSchema(
                    name=name,
                    description=getattr(cls, "description", name),
                    parameters=params,
                    required=req,
                ),
                risk=RiskMetadata(
                    risk_score=risk_s,
                    risk_level=r_level,
                    writes_files=cat == "fs" and "read" not in name,
                    executes_commands=cat == "shell",
                    blocked_in=getattr(cls, "blocked_in", []),
                ),
                implementation_cls=cls,
                aliases=[name],
                tags=[cat, name],
            )
            self._specs[name] = spec

    def _register_aliases(self) -> None:
        """Register legacy aliases and standard shortcuts."""
        # Include legacy registry aliases
        for al, canon in LEGACY_ALIASES.items():
            self._aliases[al] = canon

        # Core aliases
        aliases_map = {
            "read_file": "fs.read",
            "read": "fs.read",
            "view_file": "fs.read",
            "edit_file": "fs.edit",
            "edit": "fs.edit",
            "replace_file_content": "fs.edit",
            "write_file": "fs.write",
            "write": "fs.write",
            "bash_exec": "shell.bash",
            "bash": "shell.bash",
            "shell": "shell.bash",
            "exec_command": "shell.bash",
            "list_directory": "search.glob",
            "list_dir": "search.glob",
            "glob": "search.glob",
            "search_files": "search.grep",
            "grep": "search.grep",
            "todo": "task.todo",
            "delegate": "task.delegate",
            "ask_user": "user.ask",
            "ask": "user.ask",
        }
        for al, canon in aliases_map.items():
            self._aliases[al] = canon


# Global canonical ToolCatalog singleton
tool_catalog = ToolCatalog()
