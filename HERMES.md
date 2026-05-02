# HERMES Project Rules

## Architecture
- All model calls use keep_alive:0 (immediate VRAM release)
- Tier 1: qwen2.5-coder:7b | Tier 2: mistral:7b-instruct-q4_K_M | Tier 3: Claude Sonnet 4.6
- Never run Tier 1 and Tier 2 simultaneously
- All tool inputs validated with Pydantic v2 before execution
- Memory only written after confirmed tool exit_code=0

## Code Standards
- Python 3.12 with full type hints on every function
- Error handling on every network call and file operation
- No bare except: — always catch specific exception types
- All async functions use asyncio properly
- Every module has a corresponding test

## Security
- 15 bash security gates run before any shell command
- GITHUB_TOKEN and ANTHROPIC_API_KEY only from environment variables
- Never hardcode credentials anywhere

## File Structure
- Tools: tools/ | Memory: memory/ | Daemon: kairos/ | Models: models/ | UI: ui/
- Config: config/settings.yaml | Data: data/ (gitignored)