with open("core/agent_loop/loop.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

start_idx = None
end_idx = None

for i, line in enumerate(lines):
    if "# Deterministic loop breaker after 2 consecutive blocks" in line:
        start_idx = i
    if start_idx is not None and "self._consecutive_no_progress_blocks = 0" in line:
        end_idx = i + 1
        break

print(f"Found loop breaker block from line {start_idx + 1} to {end_idx + 1}")

replacement_lines = [
    "                                # Deterministic loop breaker after 2 consecutive blocks (Phase F)\n",
    "                                if self._consecutive_no_progress_blocks >= 2 and not getattr(self, '_recovery_triggered_this_turn', False):\n",
    "                                    self._recovery_triggered_this_turn = True\n",
    "                                    target_file_to_write = None\n",
    "                                    if unmet_reqs:\n",
    "                                        from core.agent_loop.mvp_gate import WebsiteMvpGate\n",
    "                                        tf, _ = WebsiteMvpGate.parse_scaffold_target(unmet_reqs[0])\n",
    '                                        if tf and tf not in ("npm run build", "browser_open_preview"):\n',
    "                                            target_file_to_write = tf\n",
    "\n",
    "                                    in_tier_corrections = getattr(self, '_in_tier_correction_count', 0)\n",
    "                                    # Phase F: Prioritize targeted in-tier directive before model provider failover\n",
    "                                    if in_tier_corrections < 2 and target_file_to_write:\n",
    "                                        self._in_tier_correction_count = in_tier_corrections + 1\n",
    "                                        logger.warning(\n",
    "                                            f\"AgentLoop: In-tier corrective directive issued for '{target_file_to_write}' (attempt {in_tier_corrections + 1}/2). Provider failover suppressed.\"\n",
    "                                        )\n",
    "                                        directive_obs = Observation(\n",
    "                                            observation_id=f\"obs_cor_{uuid.uuid4().hex[:6]}\",\n",
    "                                            mission_id=self._mission_id,\n",
    "                                            turn_id=turn_id,\n",
    '                                            source_type="governor",\n',
    '                                            source_id="reconciliation_controller",\n',
    "                                            success=False,\n",
    "                                            summary=f\"MANDATORY DIRECTIVE: You MUST create '{target_file_to_write}' using fs.write now. Reading '{raw_read_path}' is strictly prohibited.\",\n",
    "                                            content=(\n",
    '                                                f"CRITICAL SYSTEM DIRECTIVE:\\n"\n',
    "                                                f\"The required application file '{target_file_to_write}' is MISSING.\\n\"\n",
    "                                                f\"Do NOT call fs.read on '{raw_read_path}'.\\n\"\n",
    "                                                f\"Call fs.write immediately with target path '{target_file_to_write}' and complete code.\\n\"\n",
    "                                            ),\n",
    '                                            metadata={"code": "MANDATORY_WRITE_DIRECTIVE", "target": target_file_to_write},\n',
    "                                        )\n",
    "                                        self._record_observation(directive_obs)\n",
    "                                        self._consecutive_no_progress_blocks = 0\n",
    "                                        continue\n",
    "                                    else:\n",
    "                                        logger.warning(\n",
    '                                            f"AgentLoop: Consecutive no-progress blocks reached {self._consecutive_no_progress_blocks} with in-tier corrections exhausted. Executing bounded recovery."\n',
    "                                        )\n",
    "                                        recovery_handled = await self._execute_no_progress_recovery(\n",
    "                                            turn_id=turn_id,\n",
    "                                            mission=mission,\n",
    "                                            unmet_reqs=unmet_reqs,\n",
    "                                            rejection_reason=rejection_reason,\n",
    "                                        )\n",
]

new_lines = lines[:start_idx] + replacement_lines + lines[end_idx + 1:]
with open("core/agent_loop/loop.py", "w", encoding="utf-8") as f:
    f.writelines(new_lines)
print("Updated loop.py successfully!")
