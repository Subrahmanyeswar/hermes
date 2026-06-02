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

app = typer.Typer(help="HERMES — Local-first agentic coding framework")

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
    from models.ollama_client import OllamaClient
    from models.claude_client import ClaudeClient
    from core.intent_classifier import IntentClassifier
    
    client = OllamaClient()
    running = await client.is_running()
    models = await client.list_models() if running else []
    
    typer.echo("HERMES Configuration")
    typer.echo("=" * 40)
    typer.echo(f"Ollama: {'running' if running else 'NOT RUNNING'}")
    typer.echo(f"Available models: {', '.join(models) if models else 'none'}")
    typer.echo(f"Tier 1 required: qwen2.5-coder:7b {'✓' if any('qwen2.5-coder' in m for m in models) else '✗ NOT FOUND'}")
    typer.echo(f"Tier 2 required: mistral:7b-instruct {'✓' if any('mistral' in m for m in models) else '✗ NOT FOUND'}")
    
    claude = ClaudeClient()
    cost = claude.get_cost_summary()
    typer.echo(f"Claude API: {'available' if claude.is_available() else 'unavailable (check ANTHROPIC_API_KEY)'}")
    typer.echo(f"Claude cost: ${cost['total_spent']:.4f} / ${cost['cap']:.2f} cap")
    
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

    setup_logging(debug=debug)

    from utils.logging import setup_logging as _setup_logging
    _setup_logging(debug=debug)

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
