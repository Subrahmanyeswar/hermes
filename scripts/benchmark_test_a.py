import asyncio
import os
import json
import time
import httpx
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("NVIDIA_API_KEY")

CANDIDATES = [
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "z-ai/glm-5.3-flash",
    "nvidia/nemotron-3.5-super-vl-120b-a12b",
    "stepfun-ai/step-5-preview",
]

TEST_PROMPT = "Explain in exactly two sentences what an orbital velocity vector is and how gravity affects its direction."
SYSTEM_PROMPT = "You are an aerospace engineer. Answer directly and concisely."

async def probe_candidate(model: str, sample_idx: int):
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": TEST_PROMPT},
        ],
        "temperature": 0.0,
        "max_tokens": 256,
        "stream": True,
    }

    t0 = time.monotonic()
    connect_time = None
    first_frame_time = None
    first_reasoning_time = None
    first_content_time = None
    reasoning_chunks = []
    content_chunks = []
    error = None
    status_code = None

    try:
        # Use 35s timeout to catch stalls truthfully without hanging forever
        timeout = httpx.Timeout(connect=10.0, read=35.0, write=15.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                connect_time = time.monotonic() - t0
                status_code = resp.status_code
                if resp.status_code != 200:
                    err_body = await resp.aread()
                    error = f"HTTP {resp.status_code}: {err_body.decode(errors='replace')[:200]}"
                    return {
                        "model": model,
                        "sample": sample_idx,
                        "status": status_code,
                        "error": error,
                        "connect_s": round(connect_time, 3),
                        "total_s": round(time.monotonic() - t0, 3),
                    }

                async for line in resp.aiter_lines():
                    now = time.monotonic()
                    if not line:
                        continue
                    if line.startswith("data:"):
                        if first_frame_time is None:
                            first_frame_time = now - t0
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            choices = chunk.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                r = delta.get("reasoning_content") or delta.get("thinking")
                                if r:
                                    if first_reasoning_time is None:
                                        first_reasoning_time = now - t0
                                    reasoning_chunks.append(r)
                                c = delta.get("content")
                                if c:
                                    if first_content_time is None:
                                        first_content_time = now - t0
                                    content_chunks.append(c)
                        except Exception:
                            pass

    except httpx.ReadTimeout:
        error = "ReadTimeout (stream stalled)"
    except httpx.ConnectTimeout:
        error = "ConnectTimeout (TLS/network stalled)"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    total_time = time.monotonic() - t0
    return {
        "model": model,
        "sample": sample_idx,
        "status": status_code or "FAILED",
        "connect_s": round(connect_time, 3) if connect_time else None,
        "first_frame_s": round(first_frame_time, 3) if first_frame_time else None,
        "first_reasoning_s": round(first_reasoning_time, 3) if first_reasoning_time else None,
        "first_content_s": round(first_content_time, 3) if first_content_time else None,
        "total_s": round(total_time, 3),
        "reasoning_len": len("".join(reasoning_chunks)),
        "content_len": len("".join(content_chunks)),
        "content_preview": "".join(content_chunks)[:100].replace("\n", " "),
        "error": error,
    }

async def main():
    print("===============================================================")
    print("TEST A: FIRST-RESPONSE LATENCY BENCHMARK (3 SAMPLES PER MODEL)")
    print("===============================================================\n")

    results = []
    for model in CANDIDATES:
        print(f"\n--- Testing Candidate: {model} ---")
        for s in range(1, 4):
            print(f"  Sample {s}/3: probing...", end="", flush=True)
            res = await probe_candidate(model, s)
            results.append(res)
            if res.get("error"):
                print(f" ERROR: {res['error']} in {res['total_s']}s")
            else:
                print(
                    f" HTTP {res['status']} | Connect: {res['connect_s']}s | "
                    f"FirstFrame: {res['first_frame_s']}s | Content: {res['first_content_s']}s | "
                    f"Total: {res['total_s']}s | OutLen: {res['content_len']}"
                )
            # Short cooldown between calls to respect rate limits
            await asyncio.sleep(1.5)

    print("\n\n===============================================================")
    print("TEST A SUMMARY RESULTS:")
    print("===============================================================")
    for model in CANDIDATES:
        m_res = [r for r in results if r["model"] == model]
        successful = [r for r in m_res if not r.get("error")]
        print(f"\nModel: {model} ({len(successful)}/3 successful)")
        if successful:
            connects = [r["connect_s"] for r in successful if r["connect_s"] is not None]
            frames = [r["first_frame_s"] for r in successful if r["first_frame_s"] is not None]
            contents = [r["first_content_s"] for r in successful if r["first_content_s"] is not None]
            totals = [r["total_s"] for r in successful]
            import statistics
            print(f"  Connect latency median: {statistics.median(connects):.3f}s")
            print(f"  First frame latency median: {statistics.median(frames):.3f}s" if frames else "  First frame: N/A")
            print(f"  First content latency median: {statistics.median(contents):.3f}s" if contents else "  First content: N/A")
            print(f"  Total latency median: {statistics.median(totals):.3f}s")
        else:
            errors = [r.get("error") for r in m_res]
            print(f"  Failures: {errors}")

    out_file = "benchmark_test_a_results.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved raw results to {out_file}")

if __name__ == "__main__":
    asyncio.run(main())
