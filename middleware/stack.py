import os
from typing import List, Dict

class MiddlewareStack:
    def __init__(self):
        self.middlewares = []

    def add_middleware(self, middleware):
        self.middlewares.append(middleware)

    def process_request(self, request: Dict):
        # Trace the execution path by logging each middleware call
        for middleware in self.middlewares:
            print(f"Middleware executed: {middleware.__class__.__name__}")
            request = middleware(request)
        return request

    def ensure_header_propagation(self, request: Dict):
        # Check if 'X-Correlation-ID' header is present and ensure it's propagated
        if 'headers' not in request or 'X-Correlation-ID' not in request['headers']:
            # If missing, generate and set a new correlation ID
            request['headers']['X-Correlation-ID'] = self.generate_correlation_id()
            print("'X-Correlation-ID' header was missing and has been added.")
        return request

    def generate_correlation_id(self):
        # Generate a unique ID using UUID
        import uuid
        return str(uuid.uuid4())

# Example middleware class to demonstrate the stack
class ExampleMiddleware:
    def __init__(self):
        pass

    def __call__(selfMotivation, request):
        # Simulate processing and ensure headers are handled
        print("Example middleware processing request headers.")
        if 'headers' in request:
            print(f"Headers present: {request['headers']}")
        return request

# Main function to test the middleware stack
def main():
    stack = MiddlewareStack()
    stack.add_middleware(ExampleMiddleware())
    # Simulate an incoming request
    request = {'method': 'GET', 'path': '/', 'headers': {'Content-Type': 'application/json'}}
    # Process the request and ensure header propagation
    processed_request = stack.process_request(request)
    stack.ensure_header_propagation(processed_request)
    print("Final request headers after propagation:", processed_request['headers'])

if __name__ == "__main__":
    main()