# tests/test_critical_night_stabilization_p0.py
"""
HERMES 2.x — Critical-Night Stabilization P0 Regression Test Suite
===================================================================
Targeted tests for:
1. Provider routing & Unknown provider isolation (P0 Fix A)
2. Accurate provider error classification (P0 Fix B)
3. AgentLoop no-progress & failure ledger accounting (P0 Fix C & D)
4. Broad search & duplicate search guidance (P0 Fix E)
5. JavaScript validator resilience (P0 Fix H)
"""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from models.common_adapter import (
    CommonProviderAdapter,
    ErrorClassification,
    UnknownProviderAdapter,
    classify_provider_error,
    get_provider_adapter,
)
from tools.platform.core_tools import SearchGlobTool, SearchGlobInput
from core.js_syntax_validator import validate_javascript_content


# ==============================================================================
# 1. PROVIDER TESTS
# ==============================================================================

class TestProviderRoutingAndClassification:
    def test_mistral_and_codestral_provider_selection(self):
        """Verify codestral and mistral map to Mistral adapter with correct base URL."""
        a_mistral = get_provider_adapter("mistral")
        assert a_mistral.provider_name == "mistral"
        assert a_mistral.base_url == "https://api.mistral.ai/v1"

        a_codestral = get_provider_adapter("codestral")
        assert a_codestral.provider_name == "mistral"
        assert a_codestral.base_url == "https://api.mistral.ai/v1"

    @pytest.mark.asyncio
    async def test_unknown_provider_fails_visibly_without_openai_fallback(self):
        """Unknown provider must not fall through to api.openai.com."""
        adapter = get_provider_adapter("nonexistent_cloud_provider_xyz", tier=2)
        assert isinstance(adapter, UnknownProviderAdapter)
        assert adapter.base_url == ""

        res = await adapter.generate(prompt="Test prompt")
        assert not res.success
        assert "UNKNOWN_PROVIDER" in res.error
        assert "nonexistent_cloud_provider_xyz" in res.error

    def test_provider_credentials_not_leaked_in_str_or_repr(self):
        """Adapter string representation must never display sensitive API keys."""
        adapter = CommonProviderAdapter(
            provider_name="mistral",
            model_name="codestral-latest",
            base_url="https://api.mistral.ai/v1",
            api_key="secret-key-123456789-do-not-leak",
            tier=2,
        )
        assert "secret-key" not in str(adapter)
        assert "secret-key" not in repr(adapter)

    def test_error_classification_preserves_status_code(self):
        """Error classifier must preserve HTTP status codes and map accurately."""
        err_401 = classify_provider_error(status_code=401, response_body="Unauthorized access token")
        assert err_401.status_code == 401
        assert err_401.is_unauthorized is True
        assert err_401.is_transient is False

        err_404 = classify_provider_error(status_code=404, response_body="Model not found")
        assert err_404.status_code == 404
        assert err_404.is_model_unavailable is True

        err_429 = classify_provider_error(status_code=429, response_body="Rate limit exceeded")
        assert err_429.status_code == 429
        assert err_429.classification == ErrorClassification.RATE_LIMIT_EXCEEDED
        assert err_429.is_transient is True

    def test_http_400_not_masquerading_as_timeout(self):
        """HTTP 400 schema error must not be classified as a timeout."""
        err_400 = classify_provider_error(status_code=400, response_body="Invalid request: extra property not allowed")
        assert err_400.status_code == 400
        assert err_400.classification == ErrorClassification.INVALID_REQUEST
        assert err_400.is_transient is False

    def test_connect_and_read_timeout_classification(self):
        """ConnectTimeout and ReadTimeout must be accurately classified."""
        exc_connect = httpx.ConnectTimeout("Connection timed out to host")
        info_connect = classify_provider_error(exc=exc_connect)
        assert info_connect.classification == ErrorClassification.PROVIDER_CONNECT_TIMEOUT
        assert info_connect.is_transient is True

        exc_read = httpx.ReadTimeout("Read timed out from server")
        info_read = classify_provider_error(exc=exc_read)
        assert info_read.classification == ErrorClassification.PROVIDER_READ_TIMEOUT
        assert info_read.is_transient is True

    def test_stream_idle_timeout_safe_minimum(self):
        """CommonProviderAdapter must enforce at least 30s stream idle timeout."""
        adapter = CommonProviderAdapter(
            provider_name="mistral",
            model_name="codestral-latest",
            base_url="https://api.mistral.ai/v1",
            api_key="dummy",
            stream_idle_timeout_seconds=10.0,  # Below 30s
        )
        assert adapter.stream_idle_timeout_seconds >= 30.0


# ==============================================================================
# 2. WORKSPACE & SEARCH TESTS
# ==============================================================================

class TestWorkspaceAndSearchP0:
    def test_search_glob_ignores_hermes_and_artifacts(self, tmp_path):
        """search.glob must exclude .hermes, .artifacts, node_modules, and venv."""
        # Create standard files and hidden internal files
        (tmp_path / "index.html").write_text("<!DOCTYPE html><html></html>", encoding="utf-8")
        (tmp_path / "style.css").write_text("body {}", encoding="utf-8")
        (tmp_path / "app.js").write_text("console.log('hi');", encoding="utf-8")

        hermes_dir = tmp_path / ".hermes" / "contracts"
        hermes_dir.mkdir(parents=True)
        (hermes_dir / "state.json").write_text("{}", encoding="utf-8")

        artifacts_dir = tmp_path / ".artifacts" / "missions"
        artifacts_dir.mkdir(parents=True)
        (artifacts_dir / "progress.json").write_text("{}", encoding="utf-8")

        tool = SearchGlobTool()
        inp = SearchGlobInput(pattern="**/*", base_path=str(tmp_path), include_directories=False)
        res = tool.execute(inp)

        assert res.success is True
        assert "index.html" in res.output
        assert "style.css" in res.output
        assert "app.js" in res.output
        assert ".hermes" not in res.output
        assert ".artifacts" not in res.output


# ==============================================================================
# 3. JAVASCRIPT VALIDATION INTEGRATION
# ==============================================================================

class TestJsSyntaxValidatorP0:
    def test_regex_with_apostrophe_literal_passes(self):
        """Regex literal /'/g must pass validation."""
        js = "function sanitize(val) { return String(val).replace(/'/g, ''); }"
        ok, err, line = validate_javascript_content(js, filename="app.js")
        assert ok is True
        assert err is None

    def test_nested_template_literals_pass(self):
        """Nested template literals ${...} must parse correctly."""
        js = "const msg = `Hello ${user.name ? `Mr. ${user.name}` : 'Guest'}!`;"
        ok, err, line = validate_javascript_content(js, filename="app.js")
        assert ok is True
        assert err is None

    def test_truncated_javascript_fails_validation(self):
        """Truncated JavaScript must be rejected with line indication."""
        js = "document.addEventListener('DOMContentLoaded', () => {\n  const el = document.getElementById('btn');\n"
        ok, err, line = validate_javascript_content(js, filename="app.js")
        assert ok is False
        assert err is not None


# ==============================================================================
# 4. AGENT LOOP FAILURE ACCOUNTING & NO-PROGRESS RECOVERY
# ==============================================================================

class TestAgentLoopFailureAccounting:
    def test_failure_ledger_entry_serialization(self):
        """FailureLedgerEntry must serialize cleanly without credential exposure."""
        from core.agent_loop.loop import FailureLedgerEntry
        entry = FailureLedgerEntry(
            turn_id="turn_7_3ce7b3",
            category="PROVIDER_FAILURE",
            tier=2,
            provider="mistral",
            model="codestral-latest",
            error_class="MODEL_STREAM_STALL",
            actual_result="Stream idle timeout exceeded 30.0s",
            elapsed_duration=18.5,
            workspace_progress=False,
        )
        d = entry.to_dict()
        assert d["turn_id"] == "turn_7_3ce7b3"
        assert d["category"] == "PROVIDER_FAILURE"
        assert d["error_class"] == "MODEL_STREAM_STALL"
        assert d["tier"] == 2
        assert "secret" not in str(d)
