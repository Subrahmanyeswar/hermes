# tests/test_final_lifecycle_compatibility_remediation.py
"""
Targeted Regression Suite for:
1. EventBus strict ownership enforcement in unsubscribe_keyed.
2. RuntimeAdapter subscriber lifecycle resilience (Boolean result checks, safe retries, error redaction).
3. HermesEvent positional argument backward compatibility and keyword tracing compatibility.
"""

from dataclasses import fields
from unittest.mock import MagicMock, patch
import pytest

from core.event_bus import EventBus
from core.observability.bus_subscriber import ObservabilityBusSubscriber
from core.runtime_state.events import HermesEvent, EventType, EventSeverity
from core.server.runtime_adapter import RuntimeAdapter


# ── 1. EventBus Ownership Enforcement ─────────────────────────────────────────

class TestEventBusOwnershipEnforcement:
    """Verify that unsubscribe_keyed strictly verifies stored owner against supplied owner."""

    def test_owned_subscription_cannot_be_removed_with_omitted_owner_id(self):
        bus = EventBus(enabled=True)
        handler = MagicMock()
        registered = bus.subscribe_keyed(
            key="test.owned",
            handler=handler,
            event_types=None,
            owner_id="sub_owner_123",
        )
        assert registered is True
        assert bus.has_subscription("test.owned")

        # Attempt removal with omitted owner_id (None)
        removed = bus.unsubscribe_keyed("test.owned", owner_id=None)
        assert removed is False
        assert bus.has_subscription("test.owned")

    def test_wrong_owner_cannot_remove_subscription(self):
        bus = EventBus(enabled=True)
        handler = MagicMock()
        bus.subscribe_keyed(
            key="test.owned",
            handler=handler,
            event_types=None,
            owner_id="sub_owner_123",
        )

        # Attempt removal with incorrect owner_id
        removed = bus.unsubscribe_keyed("test.owned", owner_id="wrong_owner_456")
        assert removed is False
        assert bus.has_subscription("test.owned")

    def test_correct_owner_can_remove_subscription(self):
        bus = EventBus(enabled=True)
        handler = MagicMock()
        bus.subscribe_keyed(
            key="test.owned",
            handler=handler,
            event_types=None,
            owner_id="sub_owner_123",
        )

        # Removal with matching owner_id succeeds
        removed = bus.unsubscribe_keyed("test.owned", owner_id="sub_owner_123")
        assert removed is True
        assert not bus.has_subscription("test.owned")

    def test_unowned_keyed_registration_behavior(self):
        """Unowned keyed registration (owner_id=None) can only be removed when owner_id=None."""
        bus = EventBus(enabled=True)
        handler = MagicMock()
        registered = bus.subscribe_keyed(
            key="test.unowned",
            handler=handler,
            event_types=None,
            owner_id=None,
        )
        assert registered is True
        assert bus.has_subscription("test.unowned")

        # Wrong owner cannot remove an unowned subscription
        assert bus.unsubscribe_keyed("test.unowned", owner_id="any_owner") is False
        assert bus.has_subscription("test.unowned")

        # Explicit None matches stored None and removes cleanly
        assert bus.unsubscribe_keyed("test.unowned", owner_id=None) is True
        assert not bus.has_subscription("test.unowned")


# ── 2. RuntimeAdapter Subscriber Lifecycle ───────────────────────────────────

class TestRuntimeAdapterSubscriberLifecycle:
    """Verify RuntimeAdapter handles attach/detach outcomes, retries, and redaction safely."""

    def test_init_subscriber_attach_returning_false(self):
        """When candidate attach() returns False, subscriber is not retained."""
        bus = EventBus(enabled=True)
        adapter = RuntimeAdapter(event_bus=bus)
        # Detach existing initial subscriber
        adapter.detach_telemetry_subscriber()
        assert adapter.telemetry_subscriber is None

        with patch("core.observability.bus_subscriber.ObservabilityBusSubscriber.attach", return_value=False):
            res = adapter._init_telemetry_subscriber()
            assert res is False
            assert adapter.telemetry_subscriber is None

    def test_init_subscriber_attach_raising_exception_and_retry(self):
        """Exception during attach() logs redacted error, leaves reference None, and allows retry."""
        bus = EventBus(enabled=True)
        adapter = RuntimeAdapter(event_bus=bus)
        adapter.detach_telemetry_subscriber()
        assert adapter.telemetry_subscriber is None

        # 1. Attach raises exception with dummy secret
        with patch("core.observability.bus_subscriber.ObservabilityBusSubscriber.attach", side_effect=RuntimeError("Secret sk-proj-dummysecret123456789012345678 failed")):
            with patch("core.server.runtime_adapter.logger.warning") as mock_log:
                res = adapter._init_telemetry_subscriber()
                assert res is False
                assert adapter.telemetry_subscriber is None
                mock_log.assert_called_once()
                log_msg = mock_log.call_args[0][0]
                assert "sk-proj-dummysecret" not in log_msg
                assert "[REDACTED_SECRET]" in log_msg

        # 2. Later retry succeeds
        res_retry = adapter._init_telemetry_subscriber()
        assert res_retry is True
        assert adapter.telemetry_subscriber is not None
        assert adapter.telemetry_subscriber.is_attached is True

    def test_detach_subscriber_returning_false_preserves_reference(self):
        """When detach() returns False and subscription still exists on bus, reference is preserved."""
        bus = EventBus(enabled=True)
        adapter = RuntimeAdapter(event_bus=bus)
        assert adapter.telemetry_subscriber is not None

        # Mock detach() to return False
        with patch.object(adapter.telemetry_subscriber, "detach", return_value=False):
            res = adapter.detach_telemetry_subscriber()
            assert res is False
            # Reference must be preserved because subscription still exists
            assert adapter.telemetry_subscriber is not None

    def test_detach_subscriber_raising_exception_redacts_and_preserves_reference(self):
        """When detach() raises an exception, error is redacted and reference is preserved."""
        bus = EventBus(enabled=True)
        adapter = RuntimeAdapter(event_bus=bus)
        assert adapter.telemetry_subscriber is not None

        with patch.object(adapter.telemetry_subscriber, "detach", side_effect=RuntimeError("Detach secret Bearer dummy_bearer_token_1234567890 failed")):
            with patch("core.server.runtime_adapter.logger.warning") as mock_log:
                res = adapter.detach_telemetry_subscriber()
                assert res is False
                assert adapter.telemetry_subscriber is not None
                mock_log.assert_called_once()
                log_msg = mock_log.call_args[0][0]
                assert "dummy_bearer_token" not in log_msg
                assert "[REDACTED_SECRET]" in log_msg

    def test_successful_detach_clears_reference(self):
        bus = EventBus(enabled=True)
        adapter = RuntimeAdapter(event_bus=bus)
        assert adapter.telemetry_subscriber is not None

        res = adapter.detach_telemetry_subscriber()
        assert res is True
        assert adapter.telemetry_subscriber is None

    def test_ownership_retained_across_repeated_inits(self):
        bus = EventBus(enabled=True)
        adapter = RuntimeAdapter(event_bus=bus)
        orig_sub = adapter.telemetry_subscriber
        assert orig_sub is not None

        # Repeated init calls should retain the same subscriber instance
        res2 = adapter._init_telemetry_subscriber()
        assert res2 is True
        assert adapter.telemetry_subscriber is orig_sub


# ── 3. HermesEvent Positional Compatibility ───────────────────────────────────

class TestHermesEventPositionalCompatibility:
    """Verify that prior field ordering is preserved exactly for positional mapping."""

    def test_positional_field_mapping_unchanged(self):
        """Positional instantiations up to 28 arguments map to the exact original fields."""
        ev = HermesEvent(
            EventType.ACTION_ALLOWED,   # 0: event_type
            "m_pos_test",               # 1: mission_id
            "run_pos_test",             # 2: run_id
            2,                          # 3: attempt_number
            "task_123",                 # 4: task_id
            "ev_id_001",                # 5: event_id
            1234567890.0,               # 6: timestamp
            42,                         # 7: sequence
            "custom_source",            # 8: source
            "sess_999",                 # 9: session_id
            "req_888",                  # 10: request_id
            "turn_777",                 # 11: turn_id
            "tool_call_666",            # 12: tool_call_id
            "verif_555",                # 13: verification_id (MUST NOT BE trace_id)
            "check_444",                # 14: checkpoint_id (MUST NOT BE span_id)
            "agent_333",                # 15: agent_id (MUST NOT BE parent_span_id)
            "parent_agent_222",         # 16: parent_agent_id
            "job_111",                  # 17: job_id
            "worktree_000",             # 18: worktree_id
            "req_id_999",               # 19: requirement_id
            "acc_check_888",            # 20: acceptance_check_id
            "evidence_777",             # 21: evidence_id
            "repair_666",               # 22: repair_id
            "escalation_555",           # 23: escalation_id
            "EXECUTION",                # 24: stage
            {"test_key": "test_val"},   # 25: payload
            EventSeverity.SUCCESS,      # 26: severity
            2,                          # 27: schema_version
        )

        assert ev.event_type == EventType.ACTION_ALLOWED
        assert ev.mission_id == "m_pos_test"
        assert ev.run_id == "run_pos_test"
        assert ev.attempt_number == 2
        assert ev.task_id == "task_123"
        assert ev.event_id == "ev_id_001"
        assert ev.timestamp == 1234567890.0
        assert ev.sequence == 42
        assert ev.source == "custom_source"
        assert ev.session_id == "sess_999"
        assert ev.request_id == "req_888"
        assert ev.turn_id == "turn_777"
        assert ev.tool_call_id == "tool_call_666"

        # Prior critical fields at positions 13, 14, 15
        assert ev.verification_id == "verif_555"
        assert ev.checkpoint_id == "check_444"
        assert ev.agent_id == "agent_333"

        # Subsequent fields
        assert ev.parent_agent_id == "parent_agent_222"
        assert ev.job_id == "job_111"
        assert ev.worktree_id == "worktree_000"
        assert ev.requirement_id == "req_id_999"
        assert ev.acceptance_check_id == "acc_check_888"
        assert ev.evidence_id == "evidence_777"
        assert ev.repair_id == "repair_666"
        assert ev.escalation_id == "escalation_555"
        assert ev.stage == "EXECUTION"
        assert ev.payload == {"test_key": "test_val"}
        assert ev.severity == EventSeverity.SUCCESS
        assert ev.schema_version == 2

        # Newly appended tracing fields remain default None
        assert ev.trace_id is None
        assert ev.span_id is None
        assert ev.parent_span_id is None

    def test_keyword_tracing_arguments_work(self):
        """HermesEvent still accepts trace_id, span_id, and parent_span_id as keyword arguments."""
        ev = HermesEvent(
            event_type=EventType.TOOL_STARTED,
            mission_id="m_trace_test",
            trace_id="trace_abc_123",
            span_id="span_def_456",
            parent_span_id="span_parent_789",
        )
        assert ev.trace_id == "trace_abc_123"
        assert ev.span_id == "span_def_456"
        assert ev.parent_span_id == "span_parent_789"
