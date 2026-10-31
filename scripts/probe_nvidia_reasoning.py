# scripts/probe_nvidia_reasoning.py
import asyncio
import time
from models.nvidia_client import NvidiaClient

async def probe():
    client = NvidiaClient()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write content to a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"}
                    },
                    "required": ["path", "content"]
                }
            }
        }
    ]
    prompt = "Create a file named hello.txt containing the exact string 'Hello World'."
    
    for effort in ['none', 'low', 'high', 'default_omitted']:
        kwargs = {"tools": tools, "max_tokens": 512}
        if effort != 'default_omitted':
            kwargs["reasoning_effort"] = effort
        t0 = time.monotonic()
        try:
            resp = await client.generate(
                prompt=prompt,
                **kwargs
            )
            lat = time.monotonic() - t0
            t_calls = len(getattr(resp, "tool_calls", []) or [])
            r_len = len(getattr(resp, "reasoning", "") or "")
            print(f"effort={effort:15s} | lat={lat:5.2f}s | success={resp.success} | tools={t_calls} | reasoning_len={r_len}")
            if t_calls > 0:
                print(f"   tool_call: {resp.tool_calls[0]}")
        except Exception as e:
            print(f"effort={effort:15s} | ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(probe())
