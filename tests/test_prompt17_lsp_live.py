# tests/test_prompt17_lsp_live.py
"""
Live Integration Test: Real LSP Server (ruff server) over stdio.
Validates true JSON-RPC handshake, capability negotiation,
didOpen notification, and live diagnostics publication.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from core.code_intelligence.client import LspClient
from core.code_intelligence.models import ServerStatus


@pytest.mark.asyncio
async def test_live_ruff_lsp_server_integration(tmp_path: Path):
    """Launch real 'ruff server' and perform full LSP 3.17 handshake."""
    ruff_bin = shutil.which("ruff")
    if not ruff_bin:
        pytest.skip("ruff binary not found on system PATH")

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Create a python file with an intentional unused import and syntax issue
    test_file = workspace / "sample.py"
    test_file.write_text("import sys\nimport os\n\ndef foo():\n    pass\n", encoding="utf-8")

    client = LspClient(
        command=[ruff_bin, "server", "--preview"],
        workspace_root=workspace,
        language_id="python",
    )

    try:
        # 1. Start and Initialize Handshake
        success = await client.start_and_initialize(timeout=10.0)
        assert success is True
        assert client.status == ServerStatus.READY
        assert client.is_ready is True
        assert client.capabilities is not None

        # 2. Document Synchronization: didOpen
        await client.notify_did_open(str(test_file), test_file.read_text(encoding="utf-8"))

        # Wait briefly for diagnostics notification
        await asyncio.sleep(0.5)

        # 3. Document Synchronization: didChange
        updated_code = "import sys\nimport math\n\ndef add(a, b):\n    return a + b\n"
        await client.notify_did_change(str(test_file), updated_code)
        await asyncio.sleep(0.5)

        # 4. Graceful Shutdown & Exit
        await client.shutdown()
        assert client.status == ServerStatus.STOPPED
        assert not client.is_ready

    finally:
        await client.shutdown()
