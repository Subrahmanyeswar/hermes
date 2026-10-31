import sys
sys.path.insert(0, ".")
import asyncio
from config.model_config import TIER2_MODEL
from models.ollama_client import get_shared_ollama_client

async def test():
    c = get_shared_ollama_client()
    prompt = 'Return a JSON tool call with {"tool": "write_file", "parameters": {"path": "index.html", "content": "<h1>Hello</h1>"}}'
    # Test with think=False
    res = await c.generate(model=TIER2_MODEL, prompt=prompt, format="json", num_predict=1024, think=False)
    print("STATUS:", res.success)
    print("OUTPUT:", repr(res.text))

if __name__ == "__main__":
    asyncio.run(test())
