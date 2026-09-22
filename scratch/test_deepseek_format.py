import sys
sys.path.insert(0, ".")
import asyncio
from models.ollama_client import OllamaClient

async def test():
    client = OllamaClient()
    prompt = """Task: Create a python file smoke_test_output.py containing: def hello(): return 'world'

Respond with a JSON object:
{
  "tool": "write_file",
  "parameters": {"path": "smoke_test_output.py", "content": "def hello():\\n    return 'world'\\n"},
  "reasoning": "Create the smoke test python file",
  "explanation": "Writing file smoke_test_output.py"
}"""
    res = await client.generate(
        model="deepseek-r1:8b",
        prompt=prompt,
        keep_alive=0,
        temperature=0.0
    )
    print("Response text:\n", res.text)

asyncio.run(test())
