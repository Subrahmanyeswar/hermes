#!/usr/bin/env python3
"""
HERMES — Hierarchical Execution and Reasoning with Memory-Evolving Supervision
Local-first agentic coding framework.
Usage:
  python main.py run               # Start HERMES in interactive mode (no UI yet)
  python main.py run --mode safe   # Start in safe mode
  python main.py run --project myapp  # Start for a specific project
  python main.py test-pipeline     # Run a single test task through the pipeline
  python main.py info              # Show model and config info
"""
import sys

# ── CANONICAL RUNTIME GUARD ──────────────────────────────────────────────
if sys.version_info.major != 3 or sys.version_info.minor != 12:
    sys.stderr.write(
        f"\n[HERMES FATAL ERROR] Incompatible Python interpreter: Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}\n"
        f"HERMES strictly requires Python 3.12.x. Normal execution on Python 3.10, 3.13, etc. is rejected.\n"
        f"Launch via canonical launcher:\n"
        f"  .\\hermes.bat <args>\n"
        f"Or directly with the canonical interpreter:\n"
        f"  .\\venv\\Scripts\\python.exe main.py <args>\n\n"
    )
    sys.exit(1)

import asyncio
import json
from pathlib import Path
from typing import Optional
import typer
from loguru import logger
from textual.css.query import NoMatches

# Ensure stdout/stderr use UTF-8 on Windows to avoid UnicodeEncodeError
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

__version__ = "1.0.0-rc1"

app = typer.Typer(help="HERMES — Local-first agentic coding framework")

@app.command()
def version():
    """Show HERMES version and release status."""
    from config.model_config import (
        TIER1_PROVIDER, TIER1_MODEL,
        TIER2_PROVIDER, TIER2_MODEL,
        TIER3_PROVIDER, TIER3_MODEL,
    )
    typer.echo(f"HERMES v{__version__} (Three-Provider Production Release)")
    typer.echo("Core Runtime: FROZEN")
    typer.echo("Model Stack:")
    typer.echo(f"  • Tier 1: {TIER1_PROVIDER} / {TIER1_MODEL}")
    typer.echo(f"  • Tier 2: {TIER2_PROVIDER} / {TIER2_MODEL}")
    typer.echo(f"  • Tier 3: {TIER3_PROVIDER} / {TIER3_MODEL}")

@app.command()
def diagnostics(workspace: Optional[str] = typer.Option(None, help="Workspace directory to verify")):
    """Run full system, provider, and canonical runtime diagnostic checks."""
    from core.runtime_identity import detect_runtime_identity
    identity = detect_runtime_identity(workspace_root=workspace)
    typer.echo(identity.format_diagnostic())
    asyncio.run(_run_diagnostics())

async def _run_diagnostics():
    import os
    from config.model_config import (
        TIER1_PROVIDER, TIER1_MODEL, TIER1_BASE_URL, NVIDIA_API_KEY,
        TIER2_PROVIDER, TIER2_MODEL,
        TIER3_PROVIDER, TIER3_MODEL,
    )
    from models.ollama_client import OllamaClient
    from models.nvidia_client import NvidiaClient

    typer.echo("HERMES System Diagnostics")
    typer.echo("=" * 60)

    # 1. Environment & Python
    typer.echo(f"Python: {sys.version.split()[0]} on {sys.platform}")
    typer.echo(f"Workspace: {Path.cwd()}")

    # 2. NVIDIA NIM Tier 1 Check
    has_nv_key = bool(os.getenv("NVIDIA_API_KEY") or NVIDIA_API_KEY)
    typer.echo("\n[Tier 1] NVIDIA NIM:")
    typer.echo(f"  Provider: {TIER1_PROVIDER}")
    typer.echo(f"  Model: {TIER1_MODEL}")
    typer.echo(f"  Endpoint: {TIER1_BASE_URL}")
    typer.echo(f"  API Key: {'Configured' if has_nv_key else 'MISSING'}")
    if has_nv_key:
        nv_client = NvidiaClient(timeout_seconds=10)
        try:
            avail = await nv_client.is_available()
            typer.echo(f"  Status: {'Available' if avail else 'Unavailable'}")
        except Exception as e:
            typer.echo(f"  Status: Error checking ({e})")

    # 3. Ollama Gateway Tier 2/3 Check
    typer.echo("\n[Tier 2 & 3] Ollama Gateway:")
    ollama_client = OllamaClient()
    try:
        is_up = await asyncio.wait_for(ollama_client.is_running(), timeout=3.0)
        typer.echo(f"  Gateway: {'RUNNING (127.0.0.1:11434)' if is_up else 'NOT REACHABLE'}")
        if is_up:
            models = await ollama_client.list_models()
            typer.echo(f"  Available models: {', '.join(models) if models else 'None'}")
            t2_avail = any(TIER2_MODEL in m or "gpt-oss" in m.lower() for m in models)
            t3_avail = any(TIER3_MODEL in m or "nemotron" in m.lower() for m in models)
            typer.echo(f"  Tier 2 ({TIER2_MODEL}): {'Ready' if t2_avail else 'Ready (Cloud fallback)'}")
            typer.echo(f"  Tier 3 ({TIER3_MODEL}): {'Ready' if t3_avail else 'Ready (Cloud fallback)'}")
    except Exception as e:
        typer.echo(f"  Gateway: NOT REACHABLE ({e})")

    typer.echo("\nDiagnostic check complete.")

@app.command(name="env-check")
def env_check(
    strict: bool = typer.Option(False, "--strict", help="Exit with code 1 on any error"),
    workspace: Optional[str] = typer.Option(None, help="Workspace directory to verify"),
):
    """Validate runtime environment determinism (Python 3.12, canonical venv, dependency lock)."""
    from core.runtime_identity import validate_runtime_environment, detect_runtime_identity
    identity = detect_runtime_identity(workspace_root=workspace)
    typer.echo(identity.format_diagnostic())
    res = validate_runtime_environment(strict=False, workspace_root=workspace)
    if res["valid"]:
        typer.echo("\n[OK] Canonical Python 3.12 runtime environment is fully qualified.")
    else:
        typer.echo("\n[ERROR] Runtime environment validation failed:")
        for err in res["errors"]:
            typer.echo(f"  • {err}")
        if strict or not res["valid"]:
            raise typer.Exit(1)

@app.command(name="doctor")
def doctor(
    strict: bool = typer.Option(False, "--strict", help="Exit with code 1 on any error"),
    workspace: Optional[str] = typer.Option(None, help="Workspace directory to verify"),
):
    """Run full environment and provider health checks."""
    env_check(strict=strict, workspace=workspace)

def setup_logging(debug: bool = False):
    logger.remove()
    level = "DEBUG" if debug else "INFO"
    logger.add(sys.stderr, level=level, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
    Path("data/sessions").mkdir(parents=True, exist_ok=True)
    logger.add("data/sessions/hermes_{time:YYYY-MM-DD}.log", level="DEBUG", rotation="1 day", retention="7 days")

@app.command()
def run(
    prompt: Optional[str] = typer.Argument(None, help="User prompt to execute (headless/script mode)"),
    mode: str = typer.Option("auto", help="Permission mode: safe, plan, auto"),
    project: str = typer.Option("default", help="Project name for memory context"),
    workspace: Optional[str] = typer.Option(None, help="Workspace directory"),
    session: Optional[str] = typer.Option(None, help="Session ID to resume or run"),
    plan: bool = typer.Option(False, "--plan", help="Run in plan mode"),
    output_format: str = typer.Option("text", "--output-format", help="Output format: text, json, stream-json"),
    debug: bool = typer.Option(False, help="Enable debug logging"),
):
    """Start HERMES in headless script mode (with prompt/stdin) or interactive CLI mode."""
    from core.runtime_identity import ensure_canonical_runtime
    ensure_canonical_runtime(workspace_root=workspace)

    if mode not in ("safe", "plan", "auto"):
        typer.echo(f"Invalid mode '{mode}'. Must be: safe, plan, auto", err=True)
        raise typer.Exit(2)
    setup_logging(debug)

    # Check for stdin input if prompt not provided
    stdin_prompt = None
    if not prompt and not sys.stdin.isatty():
        try:
            stdin_prompt = sys.stdin.read().strip()
        except Exception:
            stdin_prompt = None

    effective_prompt = prompt or stdin_prompt

    if effective_prompt:
        # Headless script execution through shared ApplicationRuntimeFactory
        exit_code = asyncio.run(_run_headless(
            prompt=effective_prompt,
            workspace=workspace,
            session=session,
            plan=plan,
            output_format=output_format,
            debug=debug,
        ))
        raise typer.Exit(exit_code)

    # Interactive mode
    asyncio.run(_run_interactive(mode, project))


async def _run_headless(
    prompt: str,
    workspace: Optional[str],
    session: Optional[str],
    plan: bool,
    output_format: str,
    debug: bool,
) -> int:
    from core.runtime_factory import ApplicationRuntimeFactory, SurfaceMode
    from core.sinks import JsonSink, StreamJsonSink, TextSink

    rt = ApplicationRuntimeFactory.create_runtime(
        mode=SurfaceMode.HEADLESS,
        workspace_root=workspace,
        session_id=session,
        debug=debug,
    )

    if output_format == "json":
        sink = JsonSink()
    elif output_format == "stream-json":
        sink = StreamJsonSink()
    else:
        sink = TextSink()

    res = await rt.execute_input(prompt, sink=sink)
    return res.exit_code

async def _run_interactive(mode: str, project: str):
    from core.orchestrator import Orchestrator
    from models.ollama_client import OllamaClient, OllamaConnectionError
    
    client = OllamaClient()
    if not await client.is_running():
        typer.echo("ERROR: Ollama is not running. Start it with: ollama serve", err=True)
        raise typer.Exit(1)
    
    orch = Orchestrator(mode=mode, project=project)
    
    # Apply calibrated threshold from Week 13 calibration data
    from core.disagreement_router import load_calibrated_threshold
    calibrated_threshold = load_calibrated_threshold()
    orch.router.calibrate_threshold(calibrated_threshold)
    if calibrated_threshold != 0.72:
        typer.echo(f"Threshold calibrated to {calibrated_threshold} (from calibration data)")

    await orch.start_kairos()  # Start KAIROS before the interactive loop
    # Session resume check – see if there are RUNNING tasks from a previous session
    from kairos.task_queue import get_interrupted_tasks
    interrupted_tasks = get_interrupted_tasks()
    if interrupted_tasks:
        typer.echo("🔄 Found interrupted tasks from previous session:")
        for t in interrupted_tasks:
            typer.echo(f"   • [{t.id}] {t.title} (started at {t.started_at or 'N/A'})")
        if typer.confirm("Would you like to resume the previous session?", default=True):
            typer.echo("Resuming previous session... (functionality to be implemented)")

    try:
        typer.echo(f"HERMES ready | mode={mode.upper()} | project={project}")
        typer.echo("Type your request and press Enter. Type 'quit' or Ctrl+C to exit.")
        typer.echo("-" * 60)
        
        while True:
            try:
                user_input = input(f"\n[{mode.upper()}] > ").strip()
            except (KeyboardInterrupt, EOFError):
                typer.echo("\nExiting HERMES.")
                break
            
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                typer.echo("Exiting HERMES.")
                break
            if user_input.startswith("/mode "):
                new_mode = user_input.split()[-1]
                try:
                    orch.set_mode(new_mode)
                    mode = new_mode
                    typer.echo(f"Mode changed to: {mode.upper()}")
                except ValueError as e:
                    typer.echo(f"Error: {e}")
                continue
            
            typer.echo("Working...")
            result = await orch.run(user_input)
            typer.echo(f"\n{result.final_output}")
            if result.tool_name:
                typer.echo(f"[Tool: {result.tool_name} | Exit: {result.tool_result.exit_code if result.tool_result else 'N/A'}]")
            if result.tier3_was_called:
                cost = orch.claude.get_cost_summary()
                typer.echo(f"[Tier 3 called | Total cost: ${cost['total_spent']:.4f}]")
    finally:
        await orch.stop_kairos()

@app.command()
def test_pipeline(
    task: str = typer.Argument(default="List all files in the current directory"),
    mode: str = typer.Option("auto", help="Permission mode"),
    debug: bool = typer.Option(False, help="Enable debug logging")
):
    """Run a single task through the full 12-stage pipeline and show results."""
    setup_logging(debug)
    asyncio.run(_test_pipeline(task, mode))

async def _test_pipeline(task: str, mode: str):
    from core.orchestrator import Orchestrator
    orch = Orchestrator(mode=mode)
    typer.echo(f"Running task: {task}")
    result = await orch.run(task)
    typer.echo(f"\nSuccess: {result.success}")
    typer.echo(f"Stage reached: {result.pipeline_stage_reached}/12")
    typer.echo(f"Tool: {result.tool_name}")
    typer.echo(f"Tier 3 called: {result.tier3_was_called}")
    typer.echo(f"Latency: {result.total_latency_seconds:.2f}s")
    typer.echo(f"\nOutput:\n{result.final_output}")

@app.command()
def info():
    """Show HERMES configuration and model status."""
    asyncio.run(_show_info())

async def _show_info():
    import os
    from config.model_config import (
        TIER1_PROVIDER, TIER1_MODEL, TIER1_BASE_URL, NVIDIA_API_KEY,
        TIER2_PROVIDER, TIER2_MODEL,
        TIER3_PROVIDER, TIER3_MODEL,
    )
    from models.ollama_client import OllamaClient
    from core.intent_classifier import IntentClassifier

    typer.echo("HERMES Configuration")
    typer.echo("=" * 40)

    # Tier 1 (NVIDIA NIM)
    if TIER1_PROVIDER == "nvidia_nim":
        has_key = bool(os.getenv("NVIDIA_API_KEY") or NVIDIA_API_KEY)
        key_status = "✓ key configured" if has_key else "✗ missing NVIDIA_API_KEY"
        typer.echo(f"Tier 1 (NVIDIA NIM): {TIER1_MODEL} [{key_status}] ({TIER1_BASE_URL})")
    else:
        typer.echo(f"Tier 1 ({TIER1_PROVIDER}): {TIER1_MODEL}")

    # Ollama & Tier 2 / 3
    client = OllamaClient()
    running = await client.is_running()
    models = await client.list_models() if running else []

    typer.echo(f"Ollama: {'running' if running else 'NOT RUNNING'}")
    typer.echo(f"Available models: {', '.join(models) if models else 'none'}")
    t2_found = any(TIER2_MODEL in m or "gpt-oss" in m.lower() for m in models)
    t3_found = any(TIER3_MODEL in m or "nemotron" in m.lower() for m in models)
    typer.echo(f"Tier 2 (Ollama Cloud): {TIER2_MODEL} {'✓' if (running and t2_found) else ('✓ (cloud available)' if running else '✗ NOT RUNNING')}")
    typer.echo(f"Tier 3 ({TIER3_PROVIDER} Cloud): {TIER3_MODEL} {'✓' if (running and t3_found) else ('✓ (cloud available)' if running else '✗ NOT RUNNING')}")

    classifier = IntentClassifier("skills/")
    typer.echo(f"Skills loaded: {len(classifier.skills)}")
    typer.echo(f"Skills: {', '.join(s.skill_id for s in classifier.skills)}")

@app.command()
def ui(
    mode: str = typer.Option("auto", help="Permission mode: safe, plan, auto"),
    project: str = typer.Option("default", help="Project name for memory context"),
    workspace: Optional[str] = typer.Option(None, help="Workspace directory"),
    debug: bool = typer.Option(False, help="Enable debug logging"),
):
    """Launch the HERMES Textual TUI."""
    from core.runtime_identity import ensure_canonical_runtime
    ensure_canonical_runtime(workspace_root=workspace)

    if mode not in ("safe", "plan", "auto"):
        typer.echo(f"Invalid mode '{mode}'. Must be: safe, plan, auto", err=True)
        raise typer.Exit(1)

    from utils.logging import setup_logging as _setup_logging
    _setup_logging(debug=debug, tui=True)

    if workspace:
        from core.workspace import workspace_manager
        try:
            workspace_manager.lock(workspace)
        except Exception as e:
            typer.echo(f"Warning: could not lock workspace '{workspace}': {e}", err=True)

    from ui.app import HermesApp
    hermes_app = HermesApp(mode=mode, project=project, workspace=workspace, debug=debug)

    typer.echo(f"Launching HERMES TUI | mode={mode} | project={project} | workspace={workspace or 'interactive'}")
    typer.echo("Press Ctrl+Q to exit.")

    hermes_app.run()

@app.command()
def logs(
    query: str = typer.Argument(..., help="Search query to find in session logs"),
    max_results: int = typer.Option(20, help="Maximum results to return"),
    show_full: bool = typer.Option(False, "--full", help="Show full JSON record, not just summary")
):
    """Search HERMES session logs (Layer 3 grep access)."""
    from utils.logging import search_session_logs, SESSION_LOG_DIR
    
    typer.echo(f"Searching session logs for: {query!r}")
    typer.echo(f"Log directory: {SESSION_LOG_DIR}")
    typer.echo("-" * 60)
    
    results = search_session_logs(query, max_results=max_results)
    
    if not results:
        typer.echo("No results found.")
        return
    
    typer.echo(f"Found {len(results)} matching records:\n")
    
    for i, record in enumerate(results, 1):
        if show_full:
            typer.echo(f"[{i}] {json.dumps(record, indent=2)}")
        else:
            timestamp = record.get("timestamp", "")[:19]
            level = record.get("level", "").ljust(7)
            trace_id = record.get("trace_id", "--------")[:8]
            event = record.get("event", "")
            message = record.get("message", "")[:80]
            typer.echo(f"[{i}] {timestamp} {level} {trace_id} | {event or message}")
        
        if i < len(results):
            typer.echo("")

@app.command()
def trace(
    trace_id: str = typer.Argument(..., help="Trace ID to show full pipeline trace for"),
):
    """Show the complete pipeline trace for a specific trace_id."""
    from utils.logging import search_session_logs, SESSION_LOG_DIR

    typer.echo(f"Pipeline trace for trace_id: {trace_id}")
    typer.echo("=" * 60)

    results = search_session_logs(trace_id, max_results=100)

    if not results:
        typer.echo(f"No trace found for trace_id: {trace_id}")
        typer.echo(f"Make sure logs exist in: {SESSION_LOG_DIR}")
        typer.echo("Tip: run 'python main.py test-pipeline ...' first to generate a trace")
        return

    # Filter to only this trace_id and sort by timestamp
    trace_records = [r for r in results if r.get("trace_id") == trace_id]
    if not trace_records:
        # Try showing all results that contained the trace_id string
        trace_records = results
    trace_records.sort(key=lambda r: r.get("timestamp", ""))

    for record in trace_records:
        timestamp = record.get("timestamp", "")[:19]
        event     = record.get("event", "")
        level     = record.get("level", "INFO").ljust(7)

        if event == "pipeline_start":
            typer.echo(f"\n{timestamp} >>> PIPELINE START")
            typer.echo(f"  Request: {record.get('user_request_preview', '')}")
            typer.echo(f"  Mode: {record.get('mode', '')} | Project: {record.get('project', '')}")

        elif event == "pipeline_complete":
            typer.echo(f"\n{timestamp} === PIPELINE COMPLETE")
            typer.echo(f"  Success: {record.get('success')} | Stage: {record.get('stage_reached')}/12")
            typer.echo(
                f"  Latency: {record.get('total_latency_seconds', 0):.2f}s "
                f"| Cost: ${record.get('cost_usd', 0):.4f}"
            )

        elif event == "tier1_call":
            typer.echo(
                f"  T1: {record.get('model', '')} | "
                f"{record.get('latency_seconds', 0):.2f}s -> {record.get('parsed_tool', 'N/A')}"
            )

        elif event == "tier2_call":
            typer.echo(
                f"  T2: agree={record.get('agree')} | "
                f"conf={record.get('confidence', 0):.2f} | "
                f"escalate={record.get('escalated')}"
            )

        elif event == "tier3_call":
            typer.echo(
                f"  T3: {record.get('latency_seconds', 0):.2f}s | "
                f"${record.get('cost_usd', 0):.4f} | "
                f"success={record.get('success')}"
            )

        elif event == "tool_call":
            typer.echo(
                f"  * TOOL: {record.get('tool_name')} | "
                f"mode={record.get('mode')} | "
                f"risk={record.get('risk_score', 0):.1f}"
            )

        elif event == "tool_result":
            success_icon = "[OK]" if record.get("success") else "[FAIL]"
            typer.echo(
                f"  {success_icon} RESULT: exit={record.get('exit_code')} | "
                f"{record.get('duration_seconds', 0):.2f}s | "
                f"retry={record.get('retry_count', 0)}"
            )

        elif event and "memory" in event:
            typer.echo(
                f"  * MEMORY: {record.get('event_type')} | "
                f"facts={record.get('facts_count', 0)}"
            )

        elif event and "kairos" in event:
            typer.echo(f"  * KAIROS: {event} | {record.get('detail', '')[:60]}")

        else:
            # Generic record — show level + message preview
            msg = record.get("message", "")
            if isinstance(msg, str) and len(msg) > 0:
                # Skip raw JSONL lines (message is the full JSON)
                if not msg.startswith("{"):
                    typer.echo(f"  {level} {msg[:80]}")

@app.command()
def doctor(
    probe: bool = typer.Option(False, "--probe", help="Perform active network reachability probe"),
    workspace: Optional[str] = typer.Option(None, help="Workspace directory"),
):
    """Run comprehensive system, environment, network, and dependency diagnostics."""
    from core.commands.handlers.query_handlers import handle_doctor
    from core.commands.models import CommandIntent
    intent = CommandIntent.create("doctor", "/doctor", args=("--probe",) if probe else ())
    res = asyncio.run(handle_doctor(intent, workspace_root=workspace))
    typer.echo(res.message)
    if res.exit_code != 0:
        raise typer.Exit(res.exit_code)

@app.command()
def replay(
    target: str = typer.Argument(..., help="Session ID or trace file path to replay"),
    output_format: str = typer.Option("text", "--format", help="Presentation format: text, json, stream-json"),
    workspace: Optional[str] = typer.Option(None, help="Workspace directory"),
):
    """Replay historical session or trace file without executing any live actions."""
    from core.runtime_factory import ApplicationRuntimeFactory, SurfaceMode
    from core.sinks import JsonSink, StreamJsonSink, TextSink

    rt = ApplicationRuntimeFactory.create_runtime(SurfaceMode.REPLAY, workspace_root=workspace)
    if output_format == "json":
        sink = JsonSink()
    elif output_format == "stream-json":
        sink = StreamJsonSink()
    else:
        sink = TextSink()

    p = Path(target)
    if p.exists() and p.is_file():
        res = rt.replay_engine.replay_trace_file(p, sink=lambda evt, st: sink.on_event(evt, st))
    else:
        res = rt.replay_engine.replay_session(target, sink=lambda evt, st: sink.on_event(evt, st))

    sink.on_completed(res.final_state, exit_code=0 if res.success else 1, error_message=res.error)
    if not res.success:
        raise typer.Exit(1)

@app.command()
def status(workspace: Optional[str] = typer.Option(None, help="Workspace directory")):
    """Display authoritative runtime and session status."""
    from core.commands.handlers.query_handlers import handle_status
    from core.commands.models import CommandIntent
    intent = CommandIntent.create("status", "/status")
    res = asyncio.run(handle_status(intent, workspace_root=workspace))
    typer.echo(res.message)

@app.command()
def diff(workspace: Optional[str] = typer.Option(None, help="Workspace directory")):
    """Display uncommitted workspace diff."""
    from core.commands.handlers.query_handlers import handle_diff
    from core.commands.models import CommandIntent
    intent = CommandIntent.create("diff", "/diff")
    res = asyncio.run(handle_diff(intent, workspace_root=workspace))
    typer.echo(res.message)

@app.command()
def cost():
    """Display model token and cost accounting."""
    from core.commands.handlers.query_handlers import handle_cost
    from core.commands.models import CommandIntent
    intent = CommandIntent.create("cost", "/cost")
    res = asyncio.run(handle_cost(intent))
    typer.echo(res.message)

@app.command()
def tasks():
    """Display active task queue and background jobs."""
    from core.commands.handlers.query_handlers import handle_tasks
    from core.commands.models import CommandIntent
    intent = CommandIntent.create("tasks", "/tasks")
    res = asyncio.run(handle_tasks(intent))
    typer.echo(res.message)

@app.command(name="eval")
def run_eval(
    action: Optional[str] = typer.Argument(None, help="Action or suite: doctor, report, capability, regression, heldout, chaos, security, soak, all"),
    suite: str = typer.Option("capability", "--suite", "-s", help="Suite category: capability, regression, heldout, chaos, security, soak, all"),
    task: Optional[str] = typer.Option(None, "--task", "-t", help="Specific task ID to run"),
    trials: Optional[int] = typer.Option(None, "--trials", help="Override number of trials per task"),
    output_dir: str = typer.Option("artifacts/evals", "--output", "-o", help="Output directory for reports and results"),
    list_tasks: bool = typer.Option(False, "--list", "-l", help="List registered evaluation tasks and exit"),
    json_output: bool = typer.Option(False, "--json", help="Output results in JSON format"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
):
    """Run HERMES Evaluation Harness across capability, regression, held-out, chaos, security, or soak suites."""
    import json
    from pathlib import Path
    from core.evaluation.harness.suites import suite_registry
    from core.evaluation.harness.runner import EvalRunner
    from core.evaluation.harness.models import EvaluationCategory

    # Handle action routing
    if action:
        act_lower = action.lower()
        if act_lower == "doctor":
            typer.echo("HERMES Evaluation Suite Diagnostics (Doctor):")
            typer.echo("=" * 60)
            typer.echo(f"  • Registered Tasks: {len(suite_registry.list_all_tasks())}")
            import shutil, os
            typer.echo(f"  • Python LSP (ruff): {'✓ Available' if shutil.which('ruff') else '✗ Missing'}")
            edge_avail = os.path.exists('C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe') or bool(shutil.which('msedge'))
            typer.echo(f"  • Browser Automation (CDP): {'✓ Available (Edge)' if edge_avail else '✗ Simulated Only'}")
            from config.model_config import TIER1_MODEL, TIER2_MODEL, TIER3_MODEL
            typer.echo(f"  • Active Model Stack: T1={TIER1_MODEL} | T2={TIER2_MODEL} | T3={TIER3_MODEL}")
            typer.echo(f"  • Eval Output Root: {output_dir}")
            typer.echo("=" * 60)
            return
        elif act_lower == "report":
            typer.echo(f"HERMES Consolidated Evaluation Report ({output_dir}):")
            typer.echo("=" * 60)
            out_p = Path(output_dir)
            if not out_p.exists():
                typer.echo("No evaluation runs found.")
                return
            reports = list(out_p.glob("*/result.json"))
            if not reports:
                typer.echo("No result.json artifacts found.")
                return
            typer.echo(f"Found {len(reports)} completed task run(s):\n")
            for rep in reports:
                try:
                    data = json.loads(rep.read_text(encoding="utf-8"))
                    task_id = data.get("task_id", rep.parent.name)
                    status = data.get("overall_status", "UNKNOWN")
                    rate = data.get("pass_rate", 0.0) * 100
                    med = data.get("median_duration", 0.0)
                    icon = "[PASS]" if status == "PASS" else "[FAIL]"
                    typer.echo(f"  {icon} {task_id:<35} | Status: {status:<6} | Pass Rate: {rate:5.1f}% | Median: {med:.2f}s")
                except Exception as e:
                    typer.echo(f"  [ERR]  {rep.parent.name}: {e}")
            return
        elif act_lower in ("capability", "cap", "regression", "reg", "heldout", "held_out", "chaos", "security", "sec", "soak", "all"):
            suite = act_lower

    if list_tasks:
        tasks = suite_registry.list_all_tasks()
        typer.echo(f"Registered Evaluation Tasks ({len(tasks)}):")
        typer.echo("=" * 60)
        for t in tasks:
            typer.echo(f"  • {t.task_id:<35} [{t.category.value}] ({t.difficulty.value}) - {t.name}")
        return

    # Select tasks
    if task:
        selected_task = suite_registry.get_task(task)
        if not selected_task:
            typer.echo(f"Task '{task}' not found in registry.", err=True)
            raise typer.Exit(1)
        tasks_to_run = [selected_task]
    else:
        suite_lower = suite.lower()
        if suite_lower == "all":
            tasks_to_run = suite_registry.list_all_tasks()
        elif suite_lower in ("capability", "cap"):
            tasks_to_run = suite_registry.get_tasks_by_category(EvaluationCategory.CAPABILITY)
        elif suite_lower in ("regression", "reg"):
            tasks_to_run = suite_registry.get_tasks_by_category(EvaluationCategory.REGRESSION)
        elif suite_lower in ("heldout", "held_out"):
            tasks_to_run = suite_registry.get_tasks_by_category(EvaluationCategory.HELDOUT)
        elif suite_lower in ("chaos",):
            tasks_to_run = suite_registry.get_tasks_by_category(EvaluationCategory.CHAOS)
        elif suite_lower in ("security", "sec"):
            tasks_to_run = suite_registry.get_tasks_by_category(EvaluationCategory.SECURITY)
        elif suite_lower in ("soak",):
            tasks_to_run = suite_registry.get_tasks_by_category(EvaluationCategory.SOAK)
        else:
            typer.echo(f"Unknown suite '{suite}'. Must be: capability, regression, heldout, chaos, security, soak, all", err=True)
            raise typer.Exit(1)

    if not tasks_to_run:
        typer.echo("No tasks matched selection.", err=True)
        raise typer.Exit(1)

    runner = EvalRunner(base_runs_dir=output_dir)
    all_passed = True
    summaries = []

    typer.echo(f"Running Evaluation Suite: {len(tasks_to_run)} task(s)...")
    for t in tasks_to_run:
        if trials is not None:
            t.trial_count = trials
        typer.echo(f"\nEvaluating: {t.name} ({t.task_id}) [{t.trial_count} trial(s)]")
        res = asyncio.run(runner.run_task(t, workspace_dir=workspace))
        summaries.append(res.to_dict())
        icon = "[PASS]" if res.overall_status == "PASS" else "[FAIL]"
        typer.echo(f"  {icon} Status: {res.overall_status} | Pass Rate: {res.pass_rate*100:.1f}% | Median: {res.median_duration:.2f}s | Flaky: {res.is_flaky}")
        if res.overall_status != "PASS":
            all_passed = False
            for fm in res.failure_modes:
                typer.echo(f"      Failure mode: {fm}")

    typer.echo(f"\nEvaluation Complete. Reports written to: {output_dir}")
    if json_output:
        import json
        typer.echo(json.dumps(summaries, indent=2))

    if not all_passed:
        raise typer.Exit(1)

@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host address (strictly 127.0.0.1 / localhost)"),
    port: int = typer.Option(8765, "--port", "-p", help="Port number (default: 8765)"),
    log_level: str = typer.Option("info", "--log-level", help="Logging level"),
):
    """Start HERMES local FastAPI runtime bridge and SSE stream server."""
    from core.server.main import run_server
    run_server(host=host, port=port, log_level=log_level)

@app.command()
def gui(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host address (strictly 127.0.0.1 / localhost)"),
    port: int = typer.Option(8765, "--port", "-p", help="Port number (default: 8765)"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Start server without opening browser automatically"),
    stop: bool = typer.Option(False, "--stop", help="Stop running HERMES GUI server instance"),
    status: bool = typer.Option(False, "--status", help="Check status of HERMES GUI server"),
):
    """Launch or manage the HERMES graphical interface."""
    from core.server.launcher import launch_server, stop_server, get_port_status
    if stop:
        ok = stop_server(port=port)
        if not ok:
            raise typer.Exit(1)
        return
    if status:
        stat = get_port_status(host=host, port=port)
        import json
        typer.echo(json.dumps(stat, indent=2))
        return

    code = launch_server(host=host, port=port, open_browser=not no_browser)
    if code != 0:
        raise typer.Exit(code)

if __name__ == "__main__":
    app()


