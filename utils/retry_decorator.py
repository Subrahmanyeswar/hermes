import asyncio
import random

def with_exponential_backoff(max_retries=3, base_delay=0.1, max_delay=2.0, jitter=True):
    """
    Decorator to retry async functions with exponential backoff.
    
    Args:
        max_retries (int): Maximum number of retries.
        base_delay (float): Base delay for the first retry.
        max_delay (float): Maximum delay for any retry.
        jitter (bool): Whether to add jitter to the delay.
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            for retry_count in range(max_retries + 1):
                if retry_count > 0:
                    # Calculate delay with exponential backoff
                    base_delay_val = base_delay * (2 ** retry_count)
                    if jitter:
                        delay = base_delay_val * (1 + random.random() * 2)
                    else:
                        delay = base_delay_val
                    delay = min(delay, max_delay)
                    await asyncio.sleep(delay)
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if retry_count == max_retries:
                        raise e
                    continue
        return wrapper
    return decorator