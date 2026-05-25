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
import sys
from pathlib import Path
import typer
from loguru import logger

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

if __name__ == "__main__":
    app()
