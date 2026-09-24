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
import asyncio
import json
import sys
from pathlib import Path
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
    typer.echo(f"HERMES v{__version__} (Release Candidate 1)")
    typer.echo("Core Runtime: FROZEN")
    typer.echo("Model Stack:")
    typer.echo("  • Tier 1: nvidia_nim / z-ai/glm-5.3-flash")
    typer.echo("  • Tier 2: ollama / gpt-oss:120b-cloud")
    typer.echo("  • Tier 3: ollama / nemotron-3-ultra:cloud")

@app.command()
def diagnostics():
    """Run full system and provider diagnostic checks."""
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

def setup_logging(debug: bool = False):
    logger.remove()
    level = "DEBUG" if debug else "INFO"
    logger.add(sys.stderr, level=level, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
    Path("data/sessions").mkdir(parents=True, exist_ok=True)
    logger.add("data/sessions/hermes_{time:YYYY-MM-DD}.log", level="DEBUG", rotation="1 day", retention="7 days")

@app.command()
def run(
    mode: str = typer.Option("auto", help="Permission mode: safe, plan, auto"),
    project: str = typer.Option("default", help="Project name for memory context"),
    debug: bool = typer.Option(False, help="Enable debug logging")
):
    """Start HERMES in interactive CLI mode."""
    if mode not in ("safe", "plan", "auto"):
        typer.echo(f"Invalid mode '{mode}'. Must be: safe, plan, auto", err=True)
        raise typer.Exit(1)
    setup_logging(debug)
    asyncio.run(_run_interactive(mode, project))

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
    debug: bool = typer.Option(False, help="Enable debug logging"),
):
    """Launch the HERMES Textual TUI."""
    if mode not in ("safe", "plan", "auto"):
        typer.echo(f"Invalid mode '{mode}'. Must be: safe, plan, auto", err=True)
        raise typer.Exit(1)

    from utils.logging import setup_logging as _setup_logging
    _setup_logging(debug=debug, tui=True)

    from ui.app import HermesApp
    hermes_app = HermesApp(mode=mode, project=project, debug=debug)

    typer.echo(f"Launching HERMES TUI | mode={mode} | project={project}")
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

if __name__ == "__main__":
    app()
