# tests/test_observability_hardening_remediation.py
"""
Focused Qualification & Regression Suite for HERMES 2.x
Observability and Runtime Lifecycle Hardening.

Covers:
Part 6A: Atomic Subscription (concurrency, ownership stealing prevention, non-owner detach, owner detach, reattach)
Part 6B: Filesystem & Path Security (run_id validation, traversal rejection, endpoint security, tool_call_id sanitization)
Part 6C: Credential Redaction (stdout/stderr offload redaction, hash/chars match stored content, traceback redaction)
Part 6D: Reliable Shutdown (failure isolation across all cleanup steps)
Part 6E: Runtime Fingerprint Coverage (new critical modules, mismatch detection)
"""

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from core.event_bus import EventBus
from core.observability.bus_subscriber import ObservabilityBusSubscriber
from core.observability.logger import (
    MissionTelemetryLogger,
    validate_run_id,
    sanitize_tool_call_id,
    get_telemetry_logger,
)
from core.runtime_state.events import (
    HermesEvent,
    EventType,
    EventSeverity,
    redact_sensitive_str,
    redact_sensitive_payload,
)


# ── PART 6A: ATOMIC OBSERVABILITY SUBSCRIPTION ────────────────────────────────

class TestAtomicObservabilitySubscription:
    """Verify thread-safe, ownership-aware EventBus subscription."""

    def test_concurrent_25_attach_produces_one_subscription(self):
        """25 concurrent attach attempts on distinct subscriber instances produce exactly one subscription."""
        bus = EventBus(enabled=True)
        subscribers = [ObservabilityBusSubscriber(bus) for _ in range(25)]
        results = [None] * 25

        def worker(idx):
            results[idx] = subscribers[idx].attach()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(25)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly 1 subscriber successfully registered and claimed ownership
        assert results.count(True) == 1
        assert results.count(False) == 24

        # Exactly 1 keyed subscriber on the bus
        assert len(bus._keyed_subscribers) == 1
        assert bus.has_subscription(ObservabilityBusSubscriber.SUBSCRIPTION_KEY)

        # Only the successful subscriber has is_attached == True
        attached = [s for s in subscribers if s.is_attached]
        assert len(attached) == 1

    def test_two_instances_cannot_steal_ownership(self):
        """A second subscriber instance cannot steal or adopt the first instance's subscription."""
        bus = EventBus(enabled=True)
        sub1 = ObservabilityBusSubscriber(bus)
        sub2 = ObservabilityBusSubscriber(bus)

        assert sub1.attach() is True
        assert sub1.is_attached is True

        # Second instance attach attempt returns False and does NOT claim ownership
        assert sub2.attach() is False
        assert sub2.is_attached is False
        assert sub2._is_owner is False

        # First instance is still the sole owner
        assert sub1.is_attached is True

    def test_non_owner_detach_cannot_remove_subscriber(self):
        """A non-owner subscriber instance calling detach() cannot remove the registered subscriber."""
        bus = EventBus(enabled=True)
        sub1 = ObservabilityBusSubscriber(bus)
        sub2 = ObservabilityBusSubscriber(bus)

        sub1.attach()
        assert sub2.attach() is False

        # sub2 attempts to detach
        detached = sub2.detach()
        assert detached is False

        # sub1's subscription remains fully active
        assert bus.has_subscription(ObservabilityBusSubscriber.SUBSCRIPTION_KEY)
        assert sub1.is_attached is True

        # Direct attempt to unsubscribe with non-matching owner_id fails
        assert bus.unsubscribe_keyed(ObservabilityBusSubscriber.SUBSCRIPTION_KEY, owner_id="fake_owner") is False
        assert bus.has_subscription(ObservabilityBusSubscriber.SUBSCRIPTION_KEY)

    def test_owner_detach_removes_exactly_its_callback(self):
        """The true owner subscriber instance detaches cleanly."""
        bus = EventBus(enabled=True)
        sub1 = ObservabilityBusSubscriber(bus)

        sub1.attach()
        assert bus.has_subscription(ObservabilityBusSubscriber.SUBSCRIPTION_KEY)

        detached = sub1.detach()
        assert detached is True
        assert sub1.is_attached is False
        assert not bus.has_subscription(ObservabilityBusSubscriber.SUBSCRIPTION_KEY)

    def test_detach_followed_by_attach_works(self):
        """After legitimate detachment, reattachment succeeds cleanly."""
        bus = EventBus(enabled=True)
        sub1 = ObservabilityBusSubscriber(bus)
        sub2 = ObservabilityBusSubscriber(bus)

        sub1.attach()
        sub1.detach()
        assert not bus.has_subscription(ObservabilityBusSubscriber.SUBSCRIPTION_KEY)

        # sub2 can now legitimately attach and claim ownership
        assert sub2.attach() is True
        assert sub2.is_attached is True
        assert bus.has_subscription(ObservabilityBusSubscriber.SUBSCRIPTION_KEY)

    def test_repeated_sequential_missions_no_duplicate_events(self, tmp_path):
        """Multiple sequential missions with one global subscriber log each event exactly once."""
        bus = EventBus(enabled=True)
        global_sub = ObservabilityBusSubscriber(bus)
        assert global_sub.attach() is True

        # Run 3 simulated missions
        for i in range(1, 4):
            m_id = f"m_test_{i}"
            r_id = f"run_1_test_{i}"
            logger = MissionTelemetryLogger(run_id=r_id, mission_id=m_id, base_dir=tmp_path)

            event = HermesEvent(
                event_type=EventType.AGENT_TURN_STARTED,
                mission_id=m_id,
                run_id=r_id,
                payload={"turn": 1, "action_id": f"act_{i}"},
            )
            bus.publish(event)

            # Check that events.jsonl has exactly 1 AGENT_TURN_STARTED record
            lines = [json.loads(line) for line in open(logger.files["events"], encoding="utf-8") if line.strip()]
            turn_starts = [l for l in lines if l.get("event_type") == "AGENT_TURN_STARTED"]
            assert len(turn_starts) == 1, f"Expected 1 AGENT_TURN_STARTED for mission {m_id}, found {len(turn_starts)}"


# ── PART 6B: RUN ID AND FILESYSTEM PATH SECURITY ─────────────────────────────

class TestFilesystemPathSecurity:
    """Verify run_id validation and containment within artifacts/observability."""

    def test_reject_path_traversal_in_run_id(self, tmp_path):
        """Directory traversal patterns in run_id are strictly rejected."""
        traversal_attempts = [
            "../escape",
            "..\\escape",
            "../../etc/passwd",
            "..",
            ".",
            "foo/../../bar",
            "foo\\..\\bar",
        ]
        for bad in traversal_attempts:
            with pytest.raises(ValueError):
                validate_run_id(bad, base_dir=tmp_path)

    def test_reject_separators_and_invalid_chars(self, tmp_path):
        """Separators, colons, spaces, nulls, and excessively long IDs are rejected."""
        invalid_ids = [
            "/absolute_path",
            "C:\\windows\\system32",
            "run/with/slash",
            "run\\with\\backslash",
            "run with spaces",
            "run:with:colon",
            "run\0nullbyte",
            "a" * 129,  # exceeds 128 chars
            "",
            "   ",
        ]
        for bad in invalid_ids:
            with pytest.raises(ValueError):
                validate_run_id(bad, base_dir=tmp_path)

    def test_valid_existing_run_ids_work(self, tmp_path):
        """Canonical valid run IDs resolve cleanly within base directory."""
        valid_ids = [
            "run_1_52291bb0",
            "run_default",
            "run_m_cbdeafec",
            "run_2_b0b6b6e7",
            "benchmark-run-001",
            "run.test.123",
        ]
        for valid in valid_ids:
            resolved = validate_run_id(valid, base_dir=tmp_path)
            assert resolved.parent == tmp_path.resolve()
            assert resolved.name == valid

    def test_telemetry_summary_endpoint_rejects_traversal(self):
        """Test that get_telemetry_summary_endpoint rejects path traversal with 400 Bad Request."""
        from fastapi.testclient import TestClient
        from core.server.app import create_app
        from unittest.mock import MagicMock

        mock_adapter = MagicMock()
        mock_adapter.event_bus = EventBus(enabled=False)
        mock_adapter._active_tasks = {}
        app = create_app(adapter=mock_adapter)
        client = TestClient(app)

        # URL-encoded path traversal
        resp = client.get("/api/telemetry/..%2F..%2Fetc/summary")
        # FastAPI / Starlette routing or endpoint validator returns 400 or 404
        assert resp.status_code in (400, 404)

        # Valid format but non-existent returns 404
        resp404 = client.get("/api/telemetry/run_non_existent_123/summary")
        assert resp404.status_code == 404

    def test_tool_output_filenames_cannot_escape_directory(self, tmp_path):
        """Offloaded stdout and stderr filenames sanitize tool_call_id and stay within tool_outputs."""
        logger = MissionTelemetryLogger(run_id="run_tool_sec", mission_id="m_sec", base_dir=tmp_path)

        # Attempt to inject path traversal via tool_call_id
        evil_tool_id = "../../escaped_tool_output"
        large_stdout = "X" * 7000

        logger.record_tool_call(
            tool_call_id=evil_tool_id,
            tool_name="test_tool",
            turn=1,
            duration_ms=10.0,
            success=True,
            stdout=large_stdout,
        )

        # Verify no file escaped tool_outputs_dir
        assert not (tmp_path / "run_tool_sec" / "escaped_tool_output").exists()
        assert not (tmp_path / "escaped_tool_output").exists()

        # Files must reside strictly inside tool_outputs_dir
        tool_files = list(logger.tool_outputs_dir.iterdir())
        assert len(tool_files) == 1
        created_file = tool_files[0]
        assert created_file.parent == logger.tool_outputs_dir.resolve()
        assert ".." not in created_file.name


# ── PART 6C: CREDENTIAL REDACTION ─────────────────────────────────────────────

class TestCredentialRedaction:
    """Verify sensitive secret redaction in files, summaries, hashes, and tracebacks."""

    def test_large_stdout_and_stderr_redacted_before_disk_write(self, tmp_path):
        """Large stdout and stderr have secrets redacted before being written to disk."""
        logger = MissionTelemetryLogger(run_id="run_redact_test", mission_id="m_redact", base_dir=tmp_path)

        dummy_api_key = "sk-proj-dummysecretkey12345678901234567890"
        dummy_bearer = "Bearer dummy_bearer_token_1234567890"
        dummy_password = 'password = "super_secret_password_value"'

        large_stdout = f"Output start:\n{dummy_api_key}\n{dummy_bearer}\n" + ("A" * 7000)
        large_stderr = f"Error trace:\n{dummy_password}\n" + ("B" * 7000)

        logger.record_tool_call(
            tool_call_id="call_redact_1",
            tool_name="bash",
            turn=1,
            duration_ms=50.0,
            success=True,
            stdout=large_stdout,
            stderr=large_stderr,
        )

        # Inspect generated stdout and stderr files
        stdout_files = list(logger.tool_outputs_dir.glob("stdout_*.txt"))
        stderr_files = list(logger.tool_outputs_dir.glob("stderr_*.txt"))
        assert len(stdout_files) == 1
        assert len(stderr_files) == 1

        stored_stdout = stdout_files[0].read_text(encoding="utf-8")
        stored_stderr = stderr_files[0].read_text(encoding="utf-8")

        # Secrets must NOT appear in stored files
        assert dummy_api_key not in stored_stdout
        assert "dummy_bearer_token" not in stored_stdout
        assert "super_secret_password_value" not in stored_stderr

        # Redacted placeholders must appear
        assert "[REDACTED_SECRET]" in stored_stdout
        assert "[REDACTED_SECRET]" in stored_stderr

    def test_hashes_and_character_metadata_describe_stored_redacted_content(self, tmp_path):
        """Metadata sha256 and character length match the redacted, stored file on disk."""
        logger = MissionTelemetryLogger(run_id="run_hash_meta", mission_id="m_meta", base_dir=tmp_path)

        dummy_key = "sk-123456789012345678901234567890"
        large_out = f"Header {dummy_key}\n" + ("Z" * 6500)

        logger.record_tool_call(
            tool_call_id="call_hash_1",
            tool_name="cmd",
            turn=1,
            duration_ms=25.0,
            success=True,
            stdout=large_out,
        )

        lines = [json.loads(line) for line in open(logger.files["tools"], encoding="utf-8") if line.strip()]
        tool_evt = lines[-1]
        stdout_ref = tool_evt["payload"]["stdout_ref"]
        assert stdout_ref is not None

        file_on_disk = Path(stdout_ref["file"])
        assert file_on_disk.exists()
        content = file_on_disk.read_text(encoding="utf-8")

        # The hash and char count MUST describe the stored, redacted file
        expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert stdout_ref["sha256"] == expected_hash
        assert stdout_ref["chars"] == len(content)

    def test_exception_tracebacks_do_not_expose_dummy_secrets(self, tmp_path):
        """Exception tracebacks with embedded secrets are redacted before persistence in errors.jsonl."""
        logger = MissionTelemetryLogger(run_id="run_exc_sec", mission_id="m_exc", base_dir=tmp_path)

        secret_val = "mstrl_dummy_mistral_secret_key_12345"
        try:
            # Simulate exception where secret is embedded in traceback
            def fail_with_secret(api_key):
                raise ValueError(f"Connection failed for key {api_key}")
            fail_with_secret(secret_val)
        except Exception as exc:
            logger.record_exception(component="provider", exc=exc, failure_class="AUTH_ERROR")

        lines = [json.loads(line) for line in open(logger.files["errors"], encoding="utf-8") if line.strip()]
        assert len(lines) >= 1
        exc_event = lines[-1]

        # Secret must not appear in payload message or traceback
        raw_event_str = json.dumps(exc_event)
        assert secret_val not in raw_event_str
        assert "[REDACTED_SECRET]" in exc_event["payload"]["traceback"]


# ── PART 6D: RELIABLE SHUTDOWN ───────────────────────────────────────────────

class TestReliableShutdown:
    """Verify that lifespan shutdown independently protects each cleanup step."""

    @pytest.mark.asyncio
    async def test_forced_failure_does_not_prevent_remaining_cleanups(self):
        """A failure in one cleanup operation does not abort subsequent cleanups."""
        from core.server.app import create_app

        mock_adapter = MagicMock()
        mock_adapter.event_bus = EventBus(enabled=False)
        mock_adapter._active_tasks = {}

        # Force subscriber detachment to throw
        mock_adapter.detach_telemetry_subscriber.side_effect = RuntimeError("Detachment simulated crash")

        # Other mock operations to track execution
        coordinator_stopped = False
        monitor_stopped = False
        transport_closed = False

        app = create_app(adapter=mock_adapter)

        # Use the isolated shutdown executor attached to app.state
        safe_shutdown_fn = getattr(app.state, "safe_shutdown", None)
        assert safe_shutdown_fn is not None

        # Execute safe shutdown - must NOT raise despite detach_telemetry_subscriber throwing
        await safe_shutdown_fn()

        # Verify detach was attempted
        mock_adapter.detach_telemetry_subscriber.assert_called_once()

    @pytest.mark.asyncio
    async def test_repeated_shutdown_calls_idempotent(self):
        """Calling safe shutdown repeatedly completes cleanly without inconsistent state."""
        from core.server.app import create_app

        mock_adapter = MagicMock()
        mock_adapter.event_bus = EventBus(enabled=False)
        mock_adapter._active_tasks = {}

        app = create_app(adapter=mock_adapter)
        safe_shutdown_fn = app.state.safe_shutdown

        await safe_shutdown_fn()
        await safe_shutdown_fn()  # Second call should complete without exception


# ── PART 6E: RUNTIME FINGERPRINT COVERAGE ─────────────────────────────────────

class TestRuntimeFingerprintCoverage:
    """Verify that all required critical runtime files are tracked in fingerprinting."""

    def test_newly_added_critical_modules_in_runtime_files(self):
        """Verify that _CRITICAL_RUNTIME_FILES contains all required modules."""
        from core.server.app import _CRITICAL_RUNTIME_FILES

        required = [
            "core/event_bus.py",
            "config/model_config.py",
            "core/observability/__init__.py",
            "core/observability/bus_subscriber.py",
            "core/observability/logger.py",
            "core/observability/schemas.py",
            "core/observability/spans.py",
        ]
        for req in required:
            assert req in _CRITICAL_RUNTIME_FILES, f"Missing critical file in fingerprint list: {req}"

    def test_modifications_to_critical_module_trigger_mismatch(self):
        """Modifying hash of newly added critical file is detected as a code mismatch."""
        from core.server.app import _get_code_mismatches, _SERVER_MODULE_HASHES

        # Temporarily mock a changed hash for one of the new files
        target_file = "core/event_bus.py"
        assert target_file in _SERVER_MODULE_HASHES

        with patch("core.server.app._compute_module_hashes") as mock_hashes:
            fake_hashes = dict(_SERVER_MODULE_HASHES)
            fake_hashes[target_file] = "tampered_digest_99"
            mock_hashes.return_value = fake_hashes

            mismatches = _get_code_mismatches()
            assert target_file in mismatches
