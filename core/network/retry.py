# core/network/retry.py
"""
Retry policy and fresh-connection retry management for HERMES 2.x
Network Resilience layer.
"""

from __future__ import annotations

import random
import time
from typing import Optional
from loguru import logger

from core.network.models import (
    FailureClassification,
    is_retryable_failure,
    NON_RETRYABLE_FAILURES,
)


class RetryPolicy:
    """
    Computes bounded retry decisions, exponential backoff delays with jitter,
    and enforces remaining budget constraints.
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 5.0,
        backoff_factor: float = 2.0,
        jitter_factor: float = 0.25,
        min_attempt_budget: float = 2.0,
    ) -> None:
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.jitter_factor = jitter_factor
        self.min_attempt_budget = min_attempt_budget

    def should_retry(
        self,
        attempt_index: int,
        failure: FailureClassification,
        remaining_budget: float,
    ) -> bool:
        """
        Determine whether another physical attempt should be made.
        Returns False if max attempts reached, failure is non-retryable,
        or remaining budget is insufficient.
        """
        # Non-retryable classification check
        if failure in NON_RETRYABLE_FAILURES or not is_retryable_failure(failure):
            logger.info(f"RetryPolicy: Failure {failure.value} is non-retryable")
            return False

        # Max attempts check
        if attempt_index >= self.max_attempts:
            logger.warning(
                f"RetryPolicy: Max attempts reached ({attempt_index}/{self.max_attempts})"
            )
            return False

        # Budget check: Must have enough time for backoff delay + minimum attempt duration
        computed_delay = self.compute_delay(attempt_index, remaining_budget)
        required_time = computed_delay + self.min_attempt_budget
        if remaining_budget < required_time:
            logger.warning(
                f"RetryPolicy: Insufficient remaining budget ({remaining_budget:.2f}s < required {required_time:.2f}s)"
            )
            return False

        return True

    def compute_delay(
        self,
        attempt_index: int,
        remaining_budget: Optional[float] = None,
        seed: Optional[int] = None,
    ) -> float:
        """
        Compute exponential backoff delay with bounded jitter.
        Delay = min(max_delay, base_delay * (factor ** (attempt - 1))) +/- jitter
        Clamped to remaining budget.
        """
        exponent = max(0, attempt_index - 1)
        raw_delay = self.base_delay * (self.backoff_factor ** exponent)
        capped_delay = min(self.max_delay, raw_delay)

        # Apply jitter
        if self.jitter_factor > 0:
            rng = random.Random(seed) if seed is not None else random
            jitter_range = capped_delay * self.jitter_factor
            jitter_offset = rng.uniform(-jitter_range, jitter_range)
            delay = max(0.1, capped_delay + jitter_offset)
        else:
            delay = capped_delay

        if remaining_budget is not None:
            delay = min(delay, max(0.0, remaining_budget - self.min_attempt_budget))

        return round(delay, 3)
