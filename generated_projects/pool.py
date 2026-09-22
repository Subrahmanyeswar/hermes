import socket
import threading

class ConnectionPool:
    """A thread-safe connection pool for reusable socket connections."""

    def __init__(self, max_size=10):
        """Initialize the connection pool with a maximum size."""
        self.max_size = max_size
        self.available_sockets = []
        self.lock = threading.Lock()

    def acquire(self):
        """Acquire a socket connection from the pool or create a new one."""
        with self.lock:
            if self.available_sockets:
                return self.available_sockets.pop()
            else:
                # Create a new socket and return it
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                return sock

    def release(self, sock):
        """Release a socket connection back to the pool or close it if the pool is full."""
        with self.lock:
            if len(self.available_sockets) < self.max_size:
                self.available_sockets.append(sock)
            else:
                # If the pool is full, close the socket
                sock.close()

    def get_available_connections(self):
        """Get the number of available connections in the pool."""
        with self.lock:
            return len(self.available_sockets)

    def __del__(self):
        """Close all available sockets when the pool is destroyed."""
        with self.lock:
            for sock in self.available_sockets:
                sock.close()
            self.available_sockets = []