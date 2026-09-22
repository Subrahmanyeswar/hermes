import time
import uuid
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

class LoggerMiddleware:
    """Middleware to log HTTP requests and responses."""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        """Log request details and response."""
        start_time = time.time()
        request_id = str(uuid.uuid4())
        method = environ['REQUEST_METHOD']
        path = environ['PATH_INFO']
        status = None

        def start_response_wrapper(status, headers, exc_info=None):
            """Wrapper to capture response status."""
            nonlocal status
            status = status
            return start_response(status, headers, exc_info)

        response = self.app(environ, start_response_wrapper)
        end_time = time.time()
        duration = (end_time - start_time) * 1000

        # Log the details
        logging.info(f"Request ID: {request_id}, Method: {method}, Path: {path}, Status: {status}, Duration: {duration} ms")
        return response