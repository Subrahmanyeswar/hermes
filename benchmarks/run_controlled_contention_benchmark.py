"""
Controlled Contention Benchmark for HERMES Tier 2 Single-Request Semaphore & Monotonic Deadline.

Validates:
1. Two concurrent requests arriving at Tier 2.
2. Request 1 acquires the semaphore and performs model execution.
3. Request 2 queues for the semaphore with a configured deadline.
4. Request 2 terminates WITHIN its configured deadline (queue wait included), never exceeding it.
5. Zero semaphore leakage: after Request 1 completes, Request 3 acquires immediately and succeeds.
"""

import asyncio
import json
import time
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.ollama_client import (
    OllamaClient,
    OllamaTimeoutError,
    reset_tier2_semaphore,
)


async def run_contention_benchmark():
    sem = reset_tier2_semaphore(concurrency=1)
    client = OllamaClient(semaphore=sem)

    # Controlled mock timing to deterministically verify exact deadline boundaries:
    # Request 1 takes 2.0s
    # Request 2 has a strict 0.5s timeout budget
    r1_started = asyncio.Event()
    r1_finished = asyncio.Event()

    async def mock_post_controlled(url, json=None, timeout=None, **kwargs):
        call_id = json.get("prompt")
        if call_id == "request_1_heavy":
            r1_started.set()
            await asyncio.sleep(2.0)
            r1_finished.set()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "response": '{"tool": "write_file", "parameters": {"path": "req1.txt", "content": "ok"}}',
                "total_duration": 2_000_000_000,
            }
            return mock_resp
        elif call_id == "request_2_queued":
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"response": "req2_ok", "total_duration": 100_000_000}
            return mock_resp
        elif call_id == "request_3_subsequent":
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"response": "req3_ok", "total_duration": 50_000_000}
            return mock_resp

    with patch.object(client, "_get_client", AsyncMock()) as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = mock_post_controlled
        mock_get_client.return_value = mock_http

        print("=" * 70)
        print("HERMES CONTROLLED TIER 2 CONTENTION BENCHMARK")
        print("=" * 70)
        print("Config: Single-request semaphore (concurrency=1)")
        print("Request 1: Duration = 2.0s")
        print("Request 2: Configured Timeout = 0.50s (launched while Req 1 holds semaphore)")
        print("-" * 70)

        # Launch Request 1
        t_bench_start = time.monotonic()
        task1 = asyncio.create_task(
            client.generate(model="gpt-oss:120b-cloud", prompt="request_1_heavy", timeout_seconds=5.0)
        )
        await r1_started.wait()

        # Launch Request 2 concurrently with 0.5s deadline
        t2_launch = time.monotonic()
        r2_timed_out = False
        r2_duration = 0.0
        r2_error = ""

        try:
            await client.generate(
                model="gpt-oss:120b-cloud",
                prompt="request_2_queued",
                timeout_seconds=0.50,
            )
        except OllamaTimeoutError as exc:
            r2_duration = time.monotonic() - t2_launch
            r2_timed_out = True
            r2_error = str(exc)

        # Await Request 1 completion
        r1_result = await task1
        r1_duration = time.monotonic() - t_bench_start

        # Launch Request 3 (Subsequent verification of recovery & zero leak)
        t3_launch = time.monotonic()
        r3_result = await client.generate(
            model="gpt-oss:120b-cloud",
            prompt="request_3_subsequent",
            timeout_seconds=2.0,
        )
        r3_duration = time.monotonic() - t3_launch

        results = {
            "request_1": {
                "status": "COMPLETED",
                "duration_seconds": round(r1_duration, 4),
                "expected_duration": 2.0,
            },
            "request_2_contended": {
                "status": "TIMED_OUT" if r2_timed_out else "FAILED",
                "configured_timeout_seconds": 0.50,
                "actual_duration_seconds": round(r2_duration, 4),
                "deadline_respected": r2_duration <= 0.55,
                "error": r2_error,
            },
            "request_3_recovery": {
                "status": "COMPLETED",
                "duration_seconds": round(r3_duration, 4),
                "immediate_acquisition": r3_duration < 0.20,
            },
            "semaphore_state": {
                "concurrency_limit": 1,
                "final_available_permits": sem._value,
                "zero_leakage": sem._value == 1,
            },
        }

        print(f"Request 1 finished: {r1_duration:.3f}s (held semaphore)")
        print(f"Request 2 finished: {r2_duration:.3f}s (configured deadline: 0.50s)")
        print(f"Request 2 respected deadline: {results['request_2_contended']['deadline_respected']}")
        print(f"Request 3 recovery duration: {r3_duration:.3f}s")
        print(f"Final Semaphore Permits: {sem._value} (Zero Leak: {results['semaphore_state']['zero_leakage']})")
        print("=" * 70)

        out_path = "benchmarks/controlled_contention_results.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"Results written to {out_path}")

        assert r2_timed_out is True, "Request 2 must time out while queued"
        assert r2_duration <= 0.55, f"Request 2 duration ({r2_duration:.3f}s) exceeded deadline (0.50s)"
        assert sem._value == 1, "Semaphore was leaked"
        assert r3_result.success is True, "Subsequent request failed to acquire semaphore"
        print("ALL CONTENTION INVARIANTS VERIFIED SUCCESSFULLY.")


if __name__ == "__main__":
    asyncio.run(run_contention_benchmark())
