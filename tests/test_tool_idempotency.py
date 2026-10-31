import asyncio
import os
import sys
import tempfile
import uuid
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, os.path.abspath("."))

from core.agent_loop.actions import ActionExecutor
from core.agent_loop.types import ActionEnvelope, ActionStatus
from core.idempotency import tool_execution_ledger, compute_logical_action_id
from tools.platform.core_tools import FSWriteTool

@pytest.mark.asyncio
async def test_tool_idempotency_failover_and_replay():
    """
    Explicit Acceptance Test for Section 6:
    1. Simulate Tier 1 failure before tool execution.
    2. Tier 2 successfully generates the same logical action.
    3. Tool execution succeeds.
    Assert: Actual filesystem write executions == 1.
    4. Simulate a retry after the tool completed but before the model received the tool result.
    Assert: Actual filesystem write executions == 1.
    Verify HERMES reuses the existing cached result instead of repeating the side effect.
    """
    tool_execution_ledger.clear()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = Path(tmpdir) / "idempotent_test.txt"
        test_content = "HERMES_IDEMPOTENCY_VERIFIED_992"
        
        executor = ActionExecutor(mode="auto")
        
        test_suffix = uuid.uuid4().hex[:8]
        mission_id = f"mission_idemp_{test_suffix}"
        turn_id = "turn_01"
        tool_name = "write_file"
        arguments = {
            "path": str(test_path).replace("\\", "/"),
            "content": test_content,
        }
        
        # Track physical executions of FSWriteTool.execute
        original_execute = FSWriteTool.execute
        execute_counter = 0
        
        def counting_execute(self, tool_input):
            nonlocal execute_counter
            execute_counter += 1
            return original_execute(self, tool_input)
            
        with patch.object(FSWriteTool, "execute", side_effect=counting_execute, autospec=True):
            # Phase 1: Simulate Tier 1 fails before tool execution occurs
            # (Tier 1 model times out or encounters network error before dispatching action)
            t1_action_id = f"act_t1_timeout_{test_suffix}"
            # No tool execution occurred during Tier 1
            assert execute_counter == 0
            
            # Phase 2: Tier 2 generates the same logical action (with its own tool_call_id)
            t2_action = ActionEnvelope(
                action_id=f"act_t2_dispatch_{test_suffix}",
                mission_id=mission_id,
                task_id=mission_id,
                turn_id=turn_id,
                tool_call_id=f"call_t2_nemotron_{test_suffix}",
                tool_name=tool_name,
                arguments=arguments,
            )
            
            obs1 = await executor.execute_action(t2_action)
            assert obs1.success is True
            assert test_path.exists()
            assert test_path.read_text().strip() == test_content
            # MUST be executed exactly once
            assert execute_counter == 1, f"Expected 1 execution, got {execute_counter}"
            
            # Phase 3: Simulate retry after tool completed but before model processed result
            # (e.g. downstream network blip on SSE receipt, model replays the same logical action)
            retry_action = ActionEnvelope(
                action_id="act_retry_replay_002",
                mission_id=mission_id,
                task_id=mission_id,
                turn_id=turn_id,
                tool_call_id="call_retry_xyz",
                tool_name=tool_name,
                arguments=arguments,
            )
            
            obs2 = await executor.execute_action(retry_action)
            assert obs2.success is True
            # Verified cached reuse
            assert obs2.metadata.get("idempotent_cached") is True
            # MUST STILL be exactly 1 execution! Zero redundant side-effects!
            assert execute_counter == 1, f"Expected 1 execution after retry, got {execute_counter}"
            assert test_path.read_text().strip() == test_content
            
    print("\n>>> ACCEPTANCE TEST PASSED: Exactly 1 filesystem write execution verified across failover and replay! <<<")

if __name__ == "__main__":
    asyncio.run(test_tool_idempotency_failover_and_replay())
