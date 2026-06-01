# tests/integration/__init__.py
# Integration test package for HERMES.
# These tests run the full 12-stage pipeline with real Ollama calls.
# They require Ollama running with qwen2.5-coder:7b and mistral:7b-instruct-q4_K_M pulled.
# Run: pytest tests/integration/ -v --timeout=300
# Each test takes 10-60 seconds depending on task complexity.
