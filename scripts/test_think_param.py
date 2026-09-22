import asyncio
import httpx
import json

async def test_think():
    client = httpx.AsyncClient(timeout=60.0)
    url = "http://127.0.0.1:11434/api/generate"
    
    # Test 1: top-level think: False
    res1 = await client.post(url, json={
        "model": "deepseek-r1:8b",
        "prompt": "Return 42 as JSON: {\"answer\": 42}",
        "think": False,
        "stream": False,
        "options": {"num_predict": 100}
    })
    print("Test 1 (think: False top-level):", res1.status_code, res1.json().get("response", "")[:100])
    
    # Test 2: options think: False
    res2 = await client.post(url, json={
        "model": "deepseek-r1:8b",
        "prompt": "Return 42 as JSON: {\"answer\": 42}",
        "stream": False,
        "options": {"think": False, "num_predict": 100}
    })
    print("Test 2 (options think: False):", res2.status_code, res2.json().get("response", "")[:100])
    
    # Test 3: system prompt "Do not think. Return JSON only."
    res3 = await client.post(url, json={
        "model": "deepseek-r1:8b",
        "system": "Do not think. Do not output <think>. Return ONLY valid JSON.",
        "prompt": "Return 42 as JSON: {\"answer\": 42}",
        "stream": False,
        "options": {"num_predict": 100}
    })
    print("Test 3 (system suppress):", res3.status_code, res3.json().get("response", "")[:100])

if __name__ == "__main__":
    asyncio.run(test_think())
