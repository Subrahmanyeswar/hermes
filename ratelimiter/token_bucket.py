import threading
import time


class TokenBucketRateLimiter:
    """A rate limiter using the token bucket algorithm."
    
    def __init__(self, capacity, refill_rate):
        """Initialize the token bucket."
        :param capacity: Maximum number of tokens in the bucket."
        :param refill_rate: Rate at which tokens are added (tokens per second)."""
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity  # Start with full bucket
        self.last_refill = time.time()
        self.lock = threading.Lock()
    
    def refill(self):
        """Refill the tokens based on the elapsed time."
        with self.lock:
            now = time.time()
            time_elapsed = now - self.last_refill
            tokens_to_add = time_elapsed * self.refill_rate
            self.tokens = min(self.tokens + tokens_to_add, self.capacity)
            self.last_refill = now
    
    def consume(self, tokens=1):
        """Consume a number of tokens from the bucket."
        :param tokens: Number of tokens to consume. Default is 1."
        :return: True if tokens were consumed, False otherwise."
        with self.lock:
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            else:
                return False


# For testing, if needed
if __name__ == "__main__":
    # Example usage
    limiter = TokenBucketRateLimiter(capacity=10, refill_rate=1.0)  # 1 token per second
    print(limiter.consume())  # Should be True
    print(limiter.consume(5)) # Should be True if tokens available
    # Wait a bit and refill
    time.sleep(2)
    print(limiter.consume(10)) # Should be True after refill