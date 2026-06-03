# HERMES

**Hierarchical Execution and Reasoning with Memory-Evolving Supervision**

A local-first agentic coding framework that runs on consumer hardware (RTX 3050 6GB VRAM) without requiring continuous access to expensive frontier model APIs.

---

## What HERMES Does

HERMES takes natural language coding requests and executes them through a 12-stage pipeline:

1. You type: `create a Flask REST API with user authentication`
2. HERMES classifies the intent → loads the `flask-rest-api` skill
3. Tier 1 (Qwen2.5-Coder 7B, local, free) generates a structured tool call
4. Tier 2 (Mistral 7B, local, free) independently verifies the output
5. If they agree → execute the tool call locally at zero API cost
6. If they disagree → escalate to Claude Sonnet 4.6 for arbitration
7. Memory updated, task logged, result shown in the TUI

**78% of tasks resolve entirely locally. Only 22% require any API call.**

---

## Architecture
User Input
↓
[Stage 1-3]  Sanitise → Plan → Skill + Memory Injection
↓
[Stage 4]    Tier 1: Qwen2.5-Coder 7B (local, ~4.5GB VRAM)
Generates JSON tool call
↓
[Stage 5-6]  Security gates (15 checks) → Tool execution
↓
[Stage 7]    Tier 2: Mistral 7B (local, ~4.1GB VRAM)
Verifies tool call and output
↓
[Stage 8]    Disagreement Router
AGREE → ACCEPT (local, free)
DISAGREE → ESCALATE to Tier 3
↓
[Stage 9]    Tier 3: Claude Sonnet 4.6 (API, conditional)
Arbitrates when T1 and T2 disagree
↓
[Stage 10-12] Memory update → Task queue → Output

### Two Core Research Contributions

**1. Speculative Disagreement Routing**
Uses two 7B models from different training families (Alibaba/Qwen and Mistral AI/Mistral) to cross-verify every tool output. Cross-family verification exploits lower error correlation than same-family model ensembles. A calibrated confidence threshold θ determines when local agreement is sufficient vs when frontier API arbitration is needed.

**2. Progressive Skill Disclosure**
12 domain-specific SKILL.md files are loaded on-demand based on intent classification. A word-boundary regex classifier with a 2-match minimum and negation detection selects the appropriate skill. Ablation study shows +18pp accuracy lift on domain-specific tasks.

---

## Project Structure
hermes/
├── core/               # 12-stage pipeline orchestrator, verifier, router, planner
├── models/             # Ollama client (T1/T2), Claude client (T3)
├── tools/              # 20 tools: file, shell, git, web, memory, export, vision
├── skills/             # 12 SKILL.md files (flask, pytest, debugging, git, ...)
├── memory/             # Three-layer memory system (MEMORY.md + topics + JSONL)
├── kairos/             # Background daemon: task queue, SQLite, Triple-Gate
├── ui/                 # Textual TUI: chat panel, right panel (3 tabs), status bar
├── benchmarks/         # 50-task benchmark, ablation study, graphs, paper draft
├── tests/              # Unit tests, integration tests, failure mode tests
├── utils/              # Structured logging with trace_id per pipeline run
├── data/               # SQLite DB, session logs, benchmark results
├── config/             # settings.yaml, permissions.yaml
└── main.py             # CLI entry point

---

## Prerequisites

- Python 3.12+
- [Ollama](https://ollama.com) installed and running
- NVIDIA GPU with 6GB+ VRAM (or CPU with 16GB+ RAM, slower)
- Git

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USERNAME/hermes.git
cd hermes

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate    # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Pull the required Ollama models
ollama pull qwen2.5-coder:7b
ollama pull mistral:7b-instruct-q4_K_M

# 5. Set environment variables (never hardcode these)
export ANTHROPIC_API_KEY=sk-ant-...    # Optional: for Tier 3 escalation
export GITHUB_TOKEN=ghp_...            # Optional: for /push command

# 6. Verify installation
python main.py info
```

---

## Usage

### Terminal UI (recommended)

```bash
# Start the TUI in Auto mode (default)
python main.py ui

# Start in Safe mode (read-only, no execution)
python main.py ui --mode safe

# Start for a specific project
python main.py ui --project myapp
```

**TUI keyboard shortcuts:**
- `Ctrl+S` — Switch to Safe mode
- `Ctrl+P` — Switch to Plan mode  
- `Ctrl+A` — Switch to Auto mode
- `Ctrl+Q` — Quit

**Slash commands in the chat:**
- `/help` — Show all commands
- `/export [path]` — Export project as ZIP
- `/vscode [path]` — Open in VS Code
- `/push [dir] [branch]` — Push to GitHub
- `/screenshot <image> [html|react]` — Convert UI screenshot to code
- `/mode safe|plan|auto` — Switch mode
- `/clear` — Clear conversation

### Command Line

```bash
# Run a single task
python main.py test-pipeline "create a Flask hello world app"

# Search session logs
python main.py logs "pipeline_start" --max-results 10

# Show full trace for a specific request
python main.py trace abc12345

# Show system info
python main.py info
```

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Local-first** | T1 and T2 run on your GPU — free, private, offline-capable |
| **Smart escalation** | Only 22% of tasks need the Claude API |
| **12 skills** | Flask, pytest, debugging, git, security, docs, database, refactor, bash, React, code review, screenshot-to-code |
| **Persistent memory** | Three-layer memory survives sessions |
| **Screenshot-to-code** | Convert UI mockups to HTML/React using vision model |
| **Git integration** | Commit and push to GitHub from natural language |
| **Security gates** | 15 checks block dangerous shell commands |
| **KAIROS daemon** | Background task management with runaway detection |
| **Full observability** | Every request has a trace_id, all stages logged to JSONL |

---

## Configuration

Edit `config/settings.yaml` to configure:
- Model names and Ollama URL
- Permission levels per mode
- Memory line limits
- KAIROS gate parameters

All secrets (API keys, tokens) must be in environment variables. **Never** put secrets in `config/` files or source code.

---

## Running Tests

```bash
# Full unit test suite
pytest tests/ --ignore=tests/integration/ -q

# Integration tests (requires Ollama)
pytest tests/integration/ -v --timeout=300

# Specific test suites
pytest tests/test_tui.py -v           # TUI tests
pytest tests/test_failure_modes.py -v  # Error handling
pytest tests/test_error_handler.py -v  # Error handler

# Benchmark (full run: 2-4 hours)
python benchmarks/runner.py

# Quick benchmark (20 tasks: ~10 minutes)
python benchmarks/runner.py --quick
```

---

## Research Results

Evaluated on a 50-task benchmark across 5 difficulty levels (L1-L5):

| Metric | Value |
|--------|-------|
| HERMES task completion rate | 78% |
| Local resolution rate (free) | 78% |
| Tier 3 escalation rate | 22% |
| Skill accuracy lift (ablation) | +18pp |
| Total API cost (50 tasks) | $0.33 |
| Estimated all-Claude cost | $4.50 |
| Cost reduction | 92.7% |

See `benchmarks/paper_draft.md` for the full research paper and `benchmarks/graphs/` for all figures.

---

## Environment Variables

| Variable | Purpose | Required |
|----------|---------|----------|
| `ANTHROPIC_API_KEY` | Claude Sonnet 4.6 for Tier 3 escalation | No (T3 disabled without it) |
| `GITHUB_TOKEN` | GitHub push via `/push` command | No (push disabled without it) |

**Security**: These variables are read from the environment at runtime. They are never stored in files, logged, or committed to git. The `git_push` tool always masks the token value in logs and error messages.

---

## Acknowledgements

Built as a B.Tech Final Year capstone project in AI/ML. Models: Qwen2.5-Coder (Alibaba), Mistral 7B (Mistral AI), Claude Sonnet 4.6 (Anthropic). Runtime: Ollama, Textual, Loguru, GitPython.

Create requirements.txt with pinned versions — run this command to generate it from your actual environment:
```bash
pip freeze > requirements.txt
```
Then verify the file has at minimum these packages (versions will vary by your environment):
```bash
python -c "
required = [
    'textual', 'loguru', 'pydantic', 'gitpython',
    'httpx', 'typer', 'anthropic', 'Pillow', 'matplotlib'
]
with open('requirements.txt') as f:
    content = f.read().lower()
missing = [p for p in required if p.lower() not in content]
if missing:
    print(f'WARNING: Missing from requirements.txt: {missing}')
    print('Run: pip install ' + ' '.join(missing))
    print('Then: pip freeze > requirements.txt')
else:
    print(f'requirements.txt has all {len(required)} required packages')
"```

---

## Final Validation Script

Create the file `tests/test_submission_ready.py` with the comprehensive validation script provided in the request. See the next file creation.

---

*End of README*
