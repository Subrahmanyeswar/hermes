import asyncio
import time
import json
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

nvidia_api_key = os.getenv("NVIDIA_API_KEY", "")

async def benchmark_nim(model: str, stream: bool = True, reasoning_effort: str = "low"):
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {nvidia_api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a concise coding assistant. Respond with JSON only."},
            {"role": "user", "content": "Return a JSON object with keys 'status' and 'version'."}
        ],
        "temperature": 0.0,
        "max_tokens": 512,
        "stream": stream,
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort

    t0 = time.monotonic()
    connect_t = None
    first_chunk_t = None
    first_reasoning_t = None
    first_content_t = None
    reasoning_chunks = []
    content_chunks = []
    chunks = 0

    print(f"\n--- Benchmarking NVIDIA NIM: {model} (stream={stream}, reasoning_effort={reasoning_effort}) ---")
    try:
        timeout = httpx.Timeout(connect=5.0, read=45.0, write=15.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if stream:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    connect_t = time.monotonic() - t0
                    print(f"Connected in {connect_t:.2f}s | HTTP {resp.status_code}")
                    if resp.status_code != 200:
                        body = await resp.aread()
                        print(f"Error HTTP {resp.status_code}: {body.decode(errors='replace')[:200]}")
                        return
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        now = time.monotonic() - t0
                        if first_chunk_t is None:
                            first_chunk_t = now
                        chunk = json.loads(data_str)
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            r = delta.get("reasoning_content")
                            c = delta.get("content")
                            if r:
                                if first_reasoning_t is None:
                                    first_reasoning_t = now
                                reasoning_chunks.append(r)
                            if c:
                                if first_content_t is None:
                                    first_content_t = now
                                content_chunks.append(c)
                        chunks += 1
                total_t = time.monotonic() - t0
                print(f"Results for {model}:")
                print(f"  Connect time: {connect_t:.2f}s")
                print(f"  First chunk (TTFT): {first_chunk_t:.2f}s" if first_chunk_t else "  No chunks received")
                print(f"  First reasoning: {first_reasoning_t:.2f}s" if first_reasoning_t else "  No reasoning tokens")
                print(f"  First content: {first_content_t:.2f}s" if first_content_t else "  No content tokens")
                print(f"  Total time: {total_t:.2f}s")
                print(f"  Chunks: {chunks}, reasoning_chars={sum(len(x) for x in reasoning_chunks)}, content_chars={sum(len(x) for x in content_chunks)}")
            else:
                resp = await client.post(url, json=payload, headers=headers)
                total_t = time.monotonic() - t0
                print(f"Non-stream result: HTTP {resp.status_code} in {total_t:.2f}s")
                if resp.status_code == 200:
                    data = resp.json()
                    print(f"Content: {data['choices'][0]['message'].get('content')[:100]}")
    except Exception as exc:
        print(f"Failed after {time.monotonic() - t0:.2f}s: {type(exc).__name__}: {exc}")

async def benchmark_ollama(model: str, stream: bool = True):
    url = "http://127.0.0.1:11434/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a concise assistant. Respond with JSON only."},
            {"role": "user", "content": "Return a JSON object with keys 'status' and 'version'."}
        ],
        "format": "json",
        "stream": stream,
        "options": {"temperature": 0.0}
    }
    t0 = time.monotonic()
    first_chunk_t = None
    chunks = 0
    content = []
    print(f"\n--- Benchmarking Ollama: {model} (stream={stream}) ---")
    try:
        timeout = httpx.Timeout(connect=5.0, read=45.0, write=15.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if stream:
                async with client.stream("POST", url, json=payload) as resp:
                    connect_t = time.monotonic() - t0
                    print(f"Connected in {connect_t:.2f}s | HTTP {resp.status_code}")
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        now = time.monotonic() - t0
                        if first_chunk_t is None:
                            first_chunk_t = now
                        data = json.loads(line)
                        msg = data.get("message", {})
                        c = msg.get("content", "")
                        if c:
                            content.append(c)
                        chunks += 1
                        if data.get("done"):
                            break
                    total_t = time.monotonic() - t0
                    print(f"Results for Ollama {model}:")
                    print(f"  Connect time: {connect_t:.2f}s")
                    print(f"  First chunk (TTFT): {first_chunk_t:.2f}s" if first_chunk_t else "  No chunks")
                    print(f"  Total time: {total_t:.2f}s")
                    print(f"  Chunks: {chunks}, content_chars={sum(len(x) for x in content)}")
            else:
                resp = await client.post(url, json=payload)
                total_t = time.monotonic() - t0
                print(f"Non-stream result: HTTP {resp.status_code} in {total_t:.2f}s")
    except Exception as exc:
        print(f"Failed after {time.monotonic() - t0:.2f}s: {type(exc).__name__}: {exc}")

async def main():
    print("=== MODEL BENCHMARK HARNESS ===")
    # 1. Tier 1: GLM-5.3-flash
    await benchmark_nim("z-ai/glm-5.3-flash", stream=True, reasoning_effort="low")
    await benchmark_nim("z-ai/glm-5.3-flash", stream=True, reasoning_effort=None)
    # 2. Tier 2: Ollama gpt-oss:120b-cloud
    await benchmark_ollama("gpt-oss:120b-cloud", stream=True)
    # 3. Tier 3: Ollama nemotron-3-ultra:cloud
    await benchmark_ollama("nemotron-3-ultra:cloud", stream=True)

if __name__ == "__main__":
    asyncio.run(main())
