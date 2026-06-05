# TEST COVERAGE GAP REPORT

**Overall coverage:** 42.5% (212/499 symbols covered)

## Untested symbols per module
### audit_test_coverage
- EXCEPTION:Exception
- collect_source_symbols
- collect_test_symbols
- generate_report
- is_source_file
- map_coverage

### benchmarks.compute_metrics
- _generate_paper_table
- _print_full_summary

### benchmarks.generate_graphs
- EXCEPTION:Exception
- EXCEPTION:ImportError
- fig1_completion_rate
- fig2_escalation_rate
- fig3_skill_lift
- fig4_cost_comparison
- fig5_latency_by_difficulty
- load_or_generate_synthetic_metrics
- setup_matplotlib

### benchmarks.latency_profiler
- EXCEPTION:Exception
- LatencyReport
- LatencyReport.get_stage_stats
- StageMeasurement
- print_report

### benchmarks.runner
- BenchmarkRun
- BenchmarkRunner
- BenchmarkRunner.__init__
- BenchmarkRunner._save_results
- BenchmarkRunner.load_tasks
- EXCEPTION:Exception
- TaskResult
- _print_metrics_summary

### benchmarks.stability_audit
- AuditResult
- EXCEPTION:Exception
- audit
- check_all_skills_load
- check_error_handler_in_orchestrator
- check_kairos_state_isolation
- check_orchestrator_result_has_trace_id
- check_orchestrator_uses_parser
- check_response_parser_completeness
- check_router_uses_calibrated_threshold
- check_security_gates_complete
- check_v2_prompt_on_retry
- generate_stability_report

### core.disagreement_router
- DisagreementRouter.__init__
- EXCEPTION:(json.JSONDecodeError, KeyError, ValueError, IOError)
- RouterResult.summary

### core.error_handler
- ErrorResult.can_retry
- ErrorResult.is_final
- ErrorResult.to_log_dict

### core.intent_classifier
- EXCEPTION:(OSError, UnicodeError)
- EXCEPTION:(OSError, UnicodeError, ValueError)
- IntentClassifier.__init__
- IntentClassifier._parse_frontmatter
- IntentClassifier._word_matches

### core.orchestrator
- EXCEPTION:Exception
- Orchestrator.__init__

### core.planner
- TaskPlanner.__init__

### core.prompt_builder
- build_full_context_prompt
- estimate_prompt_tokens

### core.response_parser
- EXCEPTION:(json.JSONDecodeError, ValueError)
- EXCEPTION:(json.JSONDecodeError, ValueError, re.error)
- ParseFailure.has_json_fragment
- ParseFailure.is_plain_text
- ResponseParser._diagnose_failure
- ResponseParser._is_conversational_prose
- ResponseParser._try_direct_parse
- ResponseParser._try_emergency_extraction
- ResponseParser._try_extract_json_object
- ResponseParser._try_fix_single_quotes
- ResponseParser._try_reconstruct
- ResponseParser._try_strip_fences
- ResponseParser._validate_and_build

### core.verifier
- EXCEPTION:Exception
- EXCEPTION:JSONDecodeError
- Tier2Verifier.__init__
- Tier2Verifier._build_verification_prompt
- Tier2Verifier._parse_verification_response
- VerificationResult.__post_init__
- VerificationResult.should_escalate
- VerificationResult.summary

### generate_dead_path_report
- EXCEPTION:Exception
- safe_read_text

### generate_dead_path_report_simple
- EXCEPTION:Exception
- safe_read

### generate_system_map
- EXCEPTION:Exception

### kairos.daemon
- EXCEPTION:(ValueError, TypeError)
- EXCEPTION:CancelledError
- EXCEPTION:Exception
- KairosDaemon.__init__
- KairosDaemon._log_status_summary

### kairos.db
- EXCEPTION:Exception

### kairos.task_queue
- EXCEPTION:(ValueError, TypeError)
- EXCEPTION:Exception
- QueuedTask.can_retry
- QueuedTask.from_row
- QueuedTask.is_stuck
- _increment_kairos_counter
- detect_tool_loop_runaway
- get_interrupted_tasks

### memory.consolidator
- EXCEPTION:Exception
- resolve_contradictions

### memory.extractor
- EXCEPTION:Exception
- EXCEPTION:JSONDecodeError
- EXCEPTION:KeyError

### memory.session_logger
- EXCEPTION:Exception
- EXCEPTION:JSONDecodeError
- SessionEvent.to_jsonl_line
- SessionLogger.__init__
- SessionLogger._append_event
- SessionLogger.log_memory_update
- SessionLogger.log_tier2_verification
- SessionLogger.log_tier3_arbitration

### memory.store
- EXCEPTION:Exception
- SimpleFact

### memory.types
- MemoryIndex.get_all_lines
- MemoryIndex.get_by_type

### models.claude_client
- ClaudeClient.__init__
- ClaudeClient._init_db
- ClaudeClient._load_total_cost
- EXCEPTION:Exception

### models.ollama_client
- EXCEPTION:ConnectError
- EXCEPTION:Exception
- EXCEPTION:TimeoutException
- OllamaClient.__init__

### tools.base
- BaseTool.__init_subclass__
- ToolResult.__str__

### tools.export_tools
- EXCEPTION:Exception
- EXCEPTION:FileNotFoundError
- EXCEPTION:PermissionError
- EXCEPTION:TimeoutExpired

### tools.file_tools
- EXCEPTION:Exception
- EXCEPTION:FileNotFoundError
- EXCEPTION:NotADirectoryError
- EXCEPTION:OSError
- EXCEPTION:PermissionError
- EXCEPTION:UnicodeDecodeError
- EXCEPTION:UnicodeError
- _resolve_project_path

### tools.git_tools
- EXCEPTION:Exception
- EXCEPTION:GitCommandError
- EXCEPTION:ImportError
- EXCEPTION:InvalidGitRepositoryError

### tools.network_tools
- EXCEPTION:ConnectError
- EXCEPTION:Exception
- EXCEPTION:JSONDecodeError
- EXCEPTION:TimeoutException

### tools.prompt_tester
- EXCEPTION:Exception
- EXCEPTION:JSONDecodeError
- EXCEPTION:UnicodeEncodeError
- PromptReliabilityTester
- PromptReliabilityTester.__init__
- PromptReliabilityTester._build_test_system_prompt
- PromptReliabilityTester._try_parse_response
- PromptReliabilityTester.generate_report
- PromptReliabilityTester.print_report
- PromptTestResult

### tools.registry
- PermissionGate.__init__
- ToolNotFoundError
- ToolValidationError

### tools.security
- gate_10_hex_encoded_commands
- gate_11_crontab_modification
- gate_12_systemctl_modification
- gate_13_git_force_push
- gate_14_system_pip_install
- gate_15_recursive_wildcard_delete
- gate_1_destructive_wildcard
- gate_2_pipe_to_shell
- gate_3_sudo_escalation
- gate_4_unicode_normalise
- gate_5_path_traversal
- gate_6_protected_path
- gate_7_env_var_poisoning
- gate_8_base64_execution
- gate_9_fork_bomb

### tools.shell_tools
- EXCEPTION:Exception
- EXCEPTION:OSError
- EXCEPTION:TimeoutExpired
- _command_for_platform

### tools.vision_tools
- EXCEPTION:ConnectError
- EXCEPTION:Exception
- EXCEPTION:TimeoutException

### ui.app
- ConfirmScreen
- ConfirmScreen.compose
- ConfirmScreen.on_no
- ConfirmScreen.on_yes
- EXCEPTION:CancelledError
- EXCEPTION:Exception
- HermesApp.__init__
- HermesApp._focus_chat_input
- HermesApp._init_orchestrator
- HermesApp._set_mode
- HermesApp._update_mode_buttons
- HermesApp.action_quit
- HermesApp.action_set_mode_auto
- HermesApp.action_set_mode_plan
- HermesApp.action_set_mode_safe
- HermesApp.action_show_logs
- HermesApp.compose
- HermesApp.handle_log_record
- HermesApp.handle_orchestrator_progress
- HermesApp.on_auto_pressed
- HermesApp.on_mount
- HermesApp.on_plan_pressed
- HermesApp.on_quit_btn_pressed
- HermesApp.on_safe_pressed
- HermesApp.watch_current_mode
- HermesApp.watch_current_skill
- HermesApp.watch_is_processing
- HermesApp.watch_kairos_status
- HermesApp.watch_session_cost
- KairosStatusUpdate
- KairosStatusUpdate.__init__
- LogBar
- LogBar._tick_uptime
- LogBar.on_mount
- LogBar.update_log
- ModeChanged
- ModeChanged.__init__
- OrchestratorProgress.__init__
- OrchestratorResponse.__init__
- UserMessageSent
- UserMessageSent.__init__

### ui.panels.chat
- ChatPanel
- ChatPanel.compose
- ChatPanel.handle_input_changed
- ChatPanel.handle_mode_changed
- ChatPanel.on_mount
- ChatPanel.set_input_enabled
- EXCEPTION:Exception
- HermesMessageContent
- HermesMessageContent.__init__
- HermesMessageWidget.__init__
- HermesMessageWidget.compose
- ProcessingIndicator
- ProcessingIndicator.__init__
- ProcessingIndicator._get_stage_indicator
- ProcessingIndicator.on_click
- ProcessingIndicator.on_mount
- ProcessingIndicator.update_progress
- UserMessageWidget.__init__

### ui.panels.right_panel
- EXCEPTION:Exception
- LogTraceEntry
- LogTraceEntry.__init__
- MemoryViewPane.__init__
- MemoryViewPane.compose
- MemoryViewPane.mark_lines_as_new
- RightPanel
- RightPanel.__init__
- RightPanel.compose
- RightPanel.handle_tab_change
- RightPanel.on_mount
- TaskQueuePane
- TaskQueuePane._auto_refresh
- TaskQueuePane._render_task_row
- TaskQueuePane.compose
- TaskQueuePane.on_mount
- ToolTraceEntry.__init__
- ToolTraceEntry.update_classes
- ToolTraceEntry.update_result
- ToolTracePane
- ToolTracePane.compose

### ui.panels.status_bar
- EXCEPTION:Exception
- StatusBar._cycle_verb
- StatusBar._render_status_line
- StatusBar._start_spinner
- StatusBar._stop_spinner
- StatusBar._update_display
- StatusBar.compose
- StatusBar.on_mount
- StatusBar.set_processing
- StatusBar.update_all
- StatusBar.update_log_line
- StatusBar.watch_cost
- StatusBar.watch_kairos_status
- StatusBar.watch_mode
- StatusBar.watch_processing
- StatusBar.watch_skill
- StatusBar.watch_spinner_verb

### utils.logging
- EXCEPTION:(IOError, PermissionError)
- EXCEPTION:(TypeError, ValueError)
- EXCEPTION:Exception
- EXCEPTION:JSONDecodeError
- TraceContext.__enter__
- TraceContext.__exit__
- TraceContext.__init__
- TraceContext.elapsed_seconds
- _jsonl_sink_filter

## Missing failure‑mode tests (exceptions not exercised)
- audit_test_coverage:Exception
- generate_dead_path_report:Exception
- generate_dead_path_report_simple:Exception
- generate_system_map:Exception
- benchmarks.generate_graphs:ImportError
- benchmarks.generate_graphs:Exception
- benchmarks.latency_profiler:Exception
- benchmarks.runner:Exception
- benchmarks.stability_audit:Exception
- core.disagreement_router:(json.JSONDecodeError, KeyError, ValueError, IOError)
- core.intent_classifier:(OSError, UnicodeError)
- core.intent_classifier:(OSError, UnicodeError, ValueError)
- core.orchestrator:Exception
- core.response_parser:(json.JSONDecodeError, ValueError)
- core.response_parser:(json.JSONDecodeError, ValueError, re.error)
- core.verifier:JSONDecodeError
- core.verifier:Exception
- kairos.daemon:CancelledError
- kairos.daemon:(ValueError, TypeError)
- kairos.daemon:Exception
- kairos.db:Exception
- kairos.task_queue:(ValueError, TypeError)
- kairos.task_queue:Exception
- memory.consolidator:Exception
- memory.extractor:JSONDecodeError
- memory.extractor:KeyError
- memory.extractor:Exception
- memory.session_logger:JSONDecodeError
- memory.session_logger:Exception
- memory.store:Exception
- models.claude_client:Exception
- models.ollama_client:Exception
- models.ollama_client:ConnectError
- models.ollama_client:TimeoutException
- tools.export_tools:PermissionError
- tools.export_tools:TimeoutExpired
- tools.export_tools:FileNotFoundError
- tools.export_tools:Exception
- tools.file_tools:FileNotFoundError
- tools.file_tools:UnicodeDecodeError
- tools.file_tools:UnicodeError
- tools.file_tools:OSError
- tools.file_tools:NotADirectoryError
- tools.file_tools:PermissionError
- tools.file_tools:Exception
- tools.git_tools:GitCommandError
- tools.git_tools:InvalidGitRepositoryError
- tools.git_tools:ImportError
- tools.git_tools:Exception
- tools.network_tools:JSONDecodeError
- tools.network_tools:TimeoutException
- tools.network_tools:ConnectError
- tools.network_tools:Exception
- tools.prompt_tester:JSONDecodeError
- tools.prompt_tester:UnicodeEncodeError
- tools.prompt_tester:Exception
- tools.shell_tools:OSError
- tools.shell_tools:TimeoutExpired
- tools.shell_tools:Exception
- tools.vision_tools:Exception
- tools.vision_tools:TimeoutException
- tools.vision_tools:ConnectError
- ui.app:CancelledError
- ui.app:Exception
- ui.panels.chat:Exception
- ui.panels.right_panel:Exception
- ui.panels.status_bar:Exception
- utils.logging:(IOError, PermissionError)
- utils.logging:JSONDecodeError
- utils.logging:(TypeError, ValueError)
- utils.logging:Exception
