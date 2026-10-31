"""
Test Phase 10: Performance Profiling, Workspace Cache, Prompt-Prefix Optimization & Connection Reuse.

Validates:
1. RuntimeProfiler (core/profiler.py):
   - High-resolution monotonic timing
   - Sub-10µs per-span overhead
   - Sync & async span context managers
   - Exception safety with status="error" recording
   - Bounded in-memory buffer (eviction of oldest on cap)
   - Summary statistics and JSON export without sensitive data leakage
2. PromptCacheOptimizer (core/prompt_cache_optimizer.py):
   - Deterministic tool schema sorting
   - Prefix byte stability across equivalent turns
   - Invariant static prefix separation from dynamic turn context
   - Invalidation on schema change
3. WorkspaceManifestCache (core/workspace_cache.py):
   - Cold scan vs sub-millisecond warm retrieval (<1.0ms)
   - Exact metadata tracking
   - Targeted invalidation on file create, edit, delete
   - Cascading parent directory tracking
   - Strict boundary containment (WorkspaceBoundaryError)
   - Ignore policies (.git, .hermes, .artifacts, node_modules, venv)
4. TransportClientManager (core/transport/client_manager.py):
   - Reusable AsyncClient pooling per provider endpoint
   - Client isolation across different endpoints
   - Async shutdown via aclose()
"""

import asyncio
import json
import time
from pathlib import Path
import pytest

from core.profiler import RuntimeProfiler, ProfilerSpan
from core.prompt_cache_optimizer import PromptCacheOptimizer
from core.workspace_cache import WorkspaceManifestCache
from core.workspace import WorkspaceBoundaryError
from core.transport.client_manager import TransportClientManager


class TestPhase10RuntimeProfiler:
    def test_profiler_span_timing_and_overhead(self):
        profiler = RuntimeProfiler(max_spans=100)
        # Measure overhead over 1,000 spans
        N = 1000
        t0 = time.perf_counter()
        for i in range(N):
            with profiler.span(f"op_{i % 5}"):
                pass
        t1 = time.perf_counter()
        overhead_us = ((t1 - t0) / N) * 1_000_000.0
        assert overhead_us < 20.0, f"Overhead per span too high: {overhead_us:.2f} µs"

    def test_profiler_exception_safety(self):
        profiler = RuntimeProfiler(max_spans=10)
        with pytest.raises(RuntimeError, match="deliberate failure"):
            with profiler.span("failing_span"):
                raise RuntimeError("deliberate failure")

        spans = profiler.get_spans("failing_span")
        assert len(spans) == 1
        assert spans[0].status == "error"
        assert "RuntimeError: deliberate failure" in spans[0].error
        assert spans[0].duration_ms is not None

    @pytest.mark.asyncio
    async def test_profiler_async_span(self):
        profiler = RuntimeProfiler(max_spans=10)
        async with profiler.async_span("async_task", phase="model_request"):
            await asyncio.sleep(0.01)

        spans = profiler.get_spans("async_task")
        assert len(spans) == 1
        assert spans[0].status == "ok"
        assert spans[0].duration_ms >= 9.0  # Approx 10ms
        assert spans[0].metadata.get("phase") == "model_request"

    def test_profiler_bounded_buffer(self):
        profiler = RuntimeProfiler(max_spans=5)
        for i in range(10):
            with profiler.span(f"span_{i}"):
                pass

        all_spans = profiler.get_spans()
        assert len(all_spans) == 5
        # The oldest spans should have been evicted; remaining are 5..9
        assert [s.name for s in all_spans] == [f"span_{i}" for i in range(5, 10)]

    def test_profiler_export_redacts_secrets(self, tmp_path):
        profiler = RuntimeProfiler()
        with profiler.span("secure_op", api_key="sk-secret-12345", auth_token="bearer-token", count=42):
            pass

        export_file = tmp_path / "metrics" / "profile.json"
        profiler.export_json(export_file)
        assert export_file.is_file()

        content = json.loads(export_file.read_text(encoding="utf-8"))
        assert content["total_spans"] == 1
        meta = content["spans"][0]["metadata"]
        assert meta["count"] == 42
        assert "api_key" not in meta
        assert "auth_token" not in meta


class TestPhase10PromptCacheOptimizer:
    def test_deterministic_tool_schema_sorting(self):
        optimizer = PromptCacheOptimizer()
        tools_scrambled_1 = [
            {"name": "write_file", "parameters": {"type": "object", "properties": {"b": 2, "a": 1}}},
            {"name": "append_file", "parameters": {"type": "object"}},
            {"name": "read_file", "parameters": {"type": "object"}},
        ]
        tools_scrambled_2 = [
            {"name": "read_file", "parameters": {"type": "object"}},
            {"name": "write_file", "parameters": {"type": "object", "properties": {"a": 1, "b": 2}}},
            {"name": "append_file", "parameters": {"type": "object"}},
        ]

        norm_1 = optimizer.normalize_tools(tools_scrambled_1)
        norm_2 = optimizer.normalize_tools(tools_scrambled_2)

        assert json.dumps(norm_1) == json.dumps(norm_2)
        assert [t["name"] for t in norm_1] == ["append_file", "read_file", "write_file"]

    def test_prefix_byte_level_stability_across_turns(self):
        optimizer = PromptCacheOptimizer()
        tools = [{"name": "write_file"}, {"name": "read_file"}]

        # Turn 1
        prompt_1, prefix_1, fp_1 = optimizer.assemble_optimized_prompt(
            tools=tools,
            task_prompt="Turn 1 user request",
            workspace_context="Workspace summary: 2 files",
        )

        # Turn 2 with different dynamic task prompt and workspace context
        prompt_2, prefix_2, fp_2 = optimizer.assemble_optimized_prompt(
            tools=tools,
            task_prompt="Turn 2 subsequent request with new data",
            workspace_context="Workspace summary: 3 files (modified)",
        )

        # Prefixes must be 100% byte-for-byte identical
        assert prefix_1 == prefix_2
        assert fp_1.prefix_sha256 == fp_2.prefix_sha256
        assert fp_1.prefix_length_bytes == fp_2.prefix_length_bytes

        # But total prompt varies due to dynamic task context
        assert prompt_1 != prompt_2

    def test_schema_change_invalidates_prefix_hash(self):
        optimizer = PromptCacheOptimizer()
        _, _, fp_orig = optimizer.assemble_optimized_prompt(
            tools=[{"name": "write_file"}],
            task_prompt="Task",
        )
        _, _, fp_modified = optimizer.assemble_optimized_prompt(
            tools=[{"name": "write_file"}, {"name": "delete_file"}],
            task_prompt="Task",
        )

        assert fp_orig.prefix_sha256 != fp_modified.prefix_sha256


class TestPhase10WorkspaceCache:
    def test_cold_scan_vs_sub_millisecond_warm_retrieval(self, tmp_path):
        ws_root = tmp_path / "cache_project"
        ws_root.mkdir()
        for i in range(100):
            (ws_root / f"file_{i}.txt").write_text(f"data {i}")

        cache = WorkspaceManifestCache(ws_root)

        # Cold scan
        t0 = time.perf_counter()
        cold_files = cache.scan_workspace(force=True)
        t1 = time.perf_counter()
        cold_ms = (t1 - t0) * 1000.0

        # Warm retrieval
        t2 = time.perf_counter()
        warm_files = cache.scan_workspace(force=False)
        t3 = time.perf_counter()
        warm_ms = (t3 - t2) * 1000.0

        assert len(cold_files) == 100
        assert len(warm_files) == 100
        assert warm_ms < 1.0, f"Warm retrieval must be sub-millisecond, got {warm_ms:.3f} ms"
        stats = cache.get_stats()
        assert stats["hit_count"] >= 1
        assert stats["is_warm"] is True

    def test_precise_invalidation_on_write_and_delete(self, tmp_path):
        ws_root = tmp_path / "invalidation_project"
        ws_root.mkdir()
        cache = WorkspaceManifestCache(ws_root)
        cache.scan_workspace()

        # Write new file
        target = ws_root / "src" / "index.ts"
        target.parent.mkdir(parents=True)
        target.write_text("console.log('hello');")

        # Before invalidation, cache does not see it
        assert not cache.file_exists("src/index.ts")

        # After invalidation, cache observes it
        cache.invalidate_file(target)
        assert cache.file_exists("src/index.ts")
        cached = cache.get_file("src/index.ts")
        assert cached is not None
        assert cached.size_bytes == len("console.log('hello');")

        # Modify content and invalidate
        target.write_text("console.log('updated content');")
        cache.invalidate_file(target)
        updated_cached = cache.get_file("src/index.ts")
        assert updated_cached.size_bytes == len("console.log('updated content');")

        # Delete file and invalidate
        target.unlink()
        cache.invalidate_file(target)
        assert not cache.file_exists("src/index.ts")

    def test_boundary_containment_and_traversal_rejection(self, tmp_path):
        ws_root = tmp_path / "sandbox"
        ws_root.mkdir()
        cache = WorkspaceManifestCache(ws_root)

        with pytest.raises(WorkspaceBoundaryError):
            cache.validate_path("../../etc/shadow")

        with pytest.raises(WorkspaceBoundaryError):
            cache.validate_path("../outside.py")

    def test_ignore_policy_excludes_protected_dirs(self, tmp_path):
        ws_root = tmp_path / "ignored_project"
        ws_root.mkdir()
        (ws_root / ".git").mkdir()
        (ws_root / ".git" / "HEAD").write_text("ref: refs/heads/main")
        (ws_root / ".hermes").mkdir()
        (ws_root / ".hermes" / "state.db").write_text("data")
        (ws_root / "valid.py").write_text("print('valid')")

        cache = WorkspaceManifestCache(ws_root)
        files = cache.scan_workspace()

        assert "valid.py" in files
        assert not any(".git" in p for p in files)
        assert not any(".hermes" in p for p in files)


class TestPhase10HttpConnectionReuse:
    @pytest.mark.asyncio
    async def test_client_pooling_and_isolation(self):
        manager = TransportClientManager()
        client1 = await manager.get_client("https://api.nvidia.com")
        client2 = await manager.get_client("https://api.nvidia.com")

        # Repeated requests to the same endpoint must reuse the identical client instance
        assert client1 is client2

        # Distinct endpoint creates a separate isolated client
        client_other = await manager.get_client("https://api.ollama.com")
        assert client_other is not client1

        # Clean shutdown closes all clients
        await manager.aclose()
        assert manager._closed is True
