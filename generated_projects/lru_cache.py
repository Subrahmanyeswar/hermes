import collections
import threading

class LRUCache:
    """A thread-safe LRUCache that uses an OrderedDict and a lock for thread safety."""
    
    def __init__(self, capacity: int):
        """Initialize the LRUCache with a given capacity."""
        self.capacity = capacity
        self.cache = collections.OrderedDict()
        self.lock = threading.Lock()

    def get(self, key, default=None):
        """Retrieve the value for a given key, moving it to the end of the cache to mark it as recently used."""
        with self.lock:
            if key in self.cache:
                # Remove and re-add to move it to the end (most recently used)
                value = self.cache.pop(key)
                self.cache[key] = value
                return value
            else:
                return default

    def put(self, key, value):
        """Add or update a key-value pair in the cache, removing the oldest item if necessary."""
        with self.lock:
            if key in self.cache:
                # Update existing key
                self.cache.pop(key)
            # Check if we need to remove an item to make space
            if self.capacity > 0 and len(self.cache) >= self.capacity:
                self.cache.popitem(last=False)  # Remove the oldest item (first in OrderedDict)
            # Add the new key-value pair
            self.cache[key] = value

    def __len__(self):
        """Return the number of items in the cache."""
        with self.lock:
            return len(self.cache)