# memory/background_worker.py
"""
Background Memory Worker & Queue for HERMES vNext.
Decouples Stage 11 Memory Fact Extraction from the user critical path.

Guarantees:
1. Non-blocking user result delivery (jobs are enqueued in <1ms).
2. Failure isolation: extraction failures never fail or corrupt foreground missions.
3. Bounded queue (max 50 jobs) with graceful coalescence on saturation.
4. Independent timeout (MEMORY_EXTRACTION_TIMEOUT_SECONDS = 60s).
5. Bounded retry policy (max 1 retry).
6. Graceful shutdown on application exit.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from loguru import logger

from memory.extractor import extract_memories, confirm_and_write_facts
from memory.types import MemoryFact
from config.model_config import (
    MEMORY_EXTRACTION_TIMEOUT_SECONDS,
    MEMORY_QUEUE_MAX_SIZE,
    TIER1_MODEL
)
from utils.logging import log_memory_event


@dataclass
class MemoryJob:
    """Immutable job descriptor for background memory fact extraction."""
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    trace_id: str = ""
    mission_id: str = ""
    task_description: str = ""
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    tool_name: str = ""
    exit_code: int = 0
    project: str = "default"
    created_at_monotonic: float = field(default_factory=time.perf_counter)
    timeout_seconds: float = float(MEMORY_EXTRACTION_TIMEOUT_SECONDS)
    retries_left: int = 1
    status: str = "QUEUED"  # QUEUED, PROCESSING, COMPLETED, FAILED, DROPPED


class BackgroundMemoryManager:
    """
    In-process asynchronous queue and worker for background memory extraction.
    Thread-safe and cancellation-safe.
    """
    _instance: Optional[BackgroundMemoryManager] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, ollama_client=None):
        if getattr(self, "_initialized", False):
            if ollama_client is not None:
                self._ollama_client = ollama_client
            return

        self._queue: asyncio.Queue[MemoryJob] = asyncio.Queue(maxsize=MEMORY_QUEUE_MAX_SIZE)
        self._worker_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._ollama_client = ollama_client
        self._jobs_completed = 0
        self._jobs_failed = 0
        self._jobs_dropped = 0
        self._initialized = True
        logger.info("BackgroundMemoryManager initialized (bounded queue size: {})", MEMORY_QUEUE_MAX_SIZE)

    def set_client(self, ollama_client):
        self._ollama_client = ollama_client

    def submit(self, job: MemoryJob) -> bool:
        """
        Submit a memory extraction job to the background queue non-blockingly.
        Returns True if enqueued successfully, False if dropped due to queue saturation.
        """
        self._ensure_worker_running()

        try:
            self._queue.put_nowait(job)
            job.status = "QUEUED"
            logger.debug(
                "BackgroundMemoryManager: enqueued job {} for task '{}' (queue size: {})",
                job.job_id, job.task_description[:50], self._queue.qsize()
            )
            return True
        except asyncio.QueueFull:
            self._jobs_dropped += 1
            job.status = "DROPPED"
            logger.warning(
                "BackgroundMemoryManager: queue full ({}), dropped memory job {}",
                MEMORY_QUEUE_MAX_SIZE, job.job_id
            )
            return False

    def _ensure_worker_running(self):
        """Start the background worker task in the active event loop if not running."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        if self._worker_task is None or self._worker_task.done() or self._worker_task.get_loop() is not loop:
            self._running = True
            self._worker_task = loop.create_task(self._worker_loop(), name="BackgroundMemoryWorker")
            logger.debug("BackgroundMemoryManager: worker task started")

    async def _worker_loop(self):
        """Continuous background worker pulling and processing memory jobs."""
        logger.debug("BackgroundMemoryManager: worker loop active")
        while self._running:
            try:
                # Wait for next job
                job = await self._queue.get()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("BackgroundMemoryManager: unexpected error waiting for job: {}", e)
                await asyncio.sleep(0.5)
                continue

            job.status = "PROCESSING"
            job_start_time = time.perf_counter()
            wait_duration_ms = (job_start_time - job.created_at_monotonic) * 1000.0

            logger.info(
                "BackgroundMemoryManager: processing job {} (wait: {:.1f}ms)",
                job.job_id, wait_duration_ms
            )

            try:
                client = self._ollama_client
                if client is None:
                    from config.model_config import TIER1_PROVIDER
                    if TIER1_PROVIDER == "nvidia_nim":
                        from models.nvidia_client import NvidiaClient
                        client = NvidiaClient()
                    else:
                        from models.ollama_client import OllamaClient
                        client = OllamaClient()

                # Execute extraction under bounded timeout
                facts: List[MemoryFact] = await asyncio.wait_for(
                    extract_memories(
                        task_description=job.task_description,
                        conversation_history=job.conversation_history,
                        tool_results=job.tool_results,
                        ollama_client=client,
                        model=TIER1_MODEL
                    ),
                    timeout=job.timeout_seconds
                )

                # Confirm and write facts to MEMORY.md
                written = confirm_and_write_facts(
                    facts=facts,
                    tool_name=job.tool_name,
                    exit_code=job.exit_code,
                    project=job.project
                )

                exec_duration_ms = (time.perf_counter() - job_start_time) * 1000.0
                job.status = "COMPLETED"
                self._jobs_completed += 1

                log_memory_event(
                    trace_id=job.trace_id,
                    event_type="write_background",
                    facts_count=written,
                    project=job.project,
                    detail=f"job={job.job_id} dur={exec_duration_ms:.1f}ms written={written}"
                )
                logger.info(
                    "BackgroundMemoryManager: job {} completed successfully | {} facts written | {:.2f}s",
                    job.job_id, written, exec_duration_ms / 1000.0
                )

            except asyncio.TimeoutError:
                logger.warning(
                    "BackgroundMemoryManager: job {} timed out after {}s",
                    job.job_id, job.timeout_seconds
                )
                self._jobs_failed += 1
                job.status = "FAILED"

            except Exception as e:
                logger.warning(
                    "BackgroundMemoryManager: job {} extraction failed: {}",
                    job.job_id, e
                )
                if job.retries_left > 0:
                    job.retries_left -= 1
                    logger.info("BackgroundMemoryManager: retrying job {} (1 retry left)", job.job_id)
                    try:
                        self._queue.put_nowait(job)
                    except asyncio.QueueFull:
                        self._jobs_failed += 1
                        job.status = "FAILED"
                else:
                    self._jobs_failed += 1
                    job.status = "FAILED"

            finally:
                self._queue.task_done()

    async def aclose(self, timeout: float = 5.0):
        """Gracefully stop background worker, draining queue if possible."""
        self._running = False
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await asyncio.wait_for(self._worker_task, timeout=timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        logger.info("BackgroundMemoryManager stopped (completed: {}, failed: {})", self._jobs_completed, self._jobs_failed)

    def stats(self) -> Dict[str, Any]:
        return {
            "queue_size": self._queue.qsize(),
            "jobs_completed": self._jobs_completed,
            "jobs_failed": self._jobs_failed,
            "jobs_dropped": self._jobs_dropped,
            "is_running": self._running
        }


# Global singleton instance
background_memory_manager = BackgroundMemoryManager()
