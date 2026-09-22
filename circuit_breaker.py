import time
from collections import deque
from prometheus_client import Counter, Gauge, start_http_server

# Constants for states
close_state = "CLOSED"
open_state = "OPEN"
half_open_state = "HALF_OPEN"

# Metrics
requests_counter = Counter('cb_requests_total', 'Total number of requests made')
failures_counter = Counter('cb_failures_total', 'Total number of failed requests')
state_counter = Counter('cb_state_changes', 'Number of state changes')
failure_rate_gauge = Gauge('cb_failure_rate', 'Current failure rate')

# Fallback registry
cb_fallback_registry = {}  # Maps service name to fallback function

# Circuit Breaker class
class CircuitBreaker:
    def __init__(self, service_name, window_size=10, max_failures=5):
        self.service_name = service_name
        self.window_size = window_size  # Time window in seconds
        self.max_failures = max_failures
        self.state = close_state  # Start in CLOSED state
        self.failures = deque(maxlen=window_size)  # Stores timestamps of failures
        self.last_transition_time = time.time()
        requests_counter.labels(service=service_name).inc()

    def record_failure(self):
        current_time = time.time()
        self.failures.append(current_time)
        failures_counter.labels(service=self.service_name).inc()
        # Update failure rate
        failure_count = len(self.failures)
        failure_rate_gauge.labels(service=self.service_name).set(failure_count / self.window_size if self.window_size > 0 else 0)

    def record_success(self):
        # Reset failure count if success occurs
        self.failures.clear()
        failure_rate_gauge.labels(service=self.service_name).set(0)

    def check_state(self):
        if self.state == open_state:
            # OPEN state: Check if enough time has passed to transition to HALF_OPEN
            current_time = time.time()
            time_since_last_failure = current_time - self.failures[-1] if self.failures else float('inf')
            if time_since_last_failure > self.window_size:
                self.transition_to(half_open_state)
            return False  # Service is down
        elif self.state == half_open_state:
            # HALF_OPEN state: Check if failure rate is low enough to transition back to CLOSED
            failure_count = len(self.failures)
            if failure_count < self.max_failures / 2:
                self.transition_to(close_state)
            return True  # Service might be up
        else:  # CLOSED state
            # CLOSED state: Check if failure rate is high enough to transition to OPEN
            failure_count = len(self.failures)
            if failure_count >= self.max_failures:
                self.transition_to(open_state)
            return True  # Service is up

    def transition_to(self, new_state):
        if self.state != new_state:
            self.state = new_state
            self.last_transition_time = time.time()
            state_counter.labels(service=self.service_name, state=new_state).inc()
            print(f"Circuit breaker for {self.service_name} transitioned to {new_state}")

    def execute_with_fallback(self, func, *args, **kwargs):
        if self.state == open_state:
            # Use fallback if available
            fallback = cb_fallback_registry.get(self.service_name)
            if fallback:
                return fallback(*args, **kwargs)
            else:
                raise Exception(f"Service {self.service_name} is down. Circuit breaker is OPEN.")
        elif self.state == half_open_state:
            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception as e:
                self.record_failure()
                raise e
        else:  # CLOSED state
            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception as e:
                self.record_failure()
                # No transition yet, wait for next check
                return None

# Initialize Prometheus metrics
start_http_server(8000)

# Example usage
if __name__ == '__main__':
    # Register a fallback function
    def fallback_func():
        return "Fallback response"
    cb_fallback_registry["example_service"] = fallback_func

    # Create a circuit breaker instance
    breaker = CircuitBreaker("example_service", window_size=10, max_failures=5)

    # Simulate service calls
    def failing_service():
        if time.time() % 10 < 0.1:  # Fail occasionally
            raise Exception("Service unavailable")
        return "Success"

    # Execute with circuit breaker
    try:
        response = breaker.execute_with_fallback(failing_service)
        print(f"Response: {response}")
    except Exception as e:
        print(f"Error: {e}")

    # Keep the server running
    while True:
        time.sleep(1)