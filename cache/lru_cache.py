from collections import OrderedDict

class LRUCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.cache = OrderedDict()
        self.eviction_callback = None  # Callback function for eviction notifications

    def get(self, key):
        if key not in self.cache:
            return None
        value = self.cache[key]
        self.cache.move_to_end(key)  # Update to most recently used
        return value

    def put(self, key, value):
        if key in self.cache:
            self.cache.move_to_end(key)  # Update to most recently used
            self.cache[key] = value
        else:
            if len(self.cache) >= self.capacity:
                evicted_key, evicted_value = self.cache.popitem(last=False)  # Remove least recently used
                if self.eviction_callback:
                    self.eviction_callback(evicted_key, evicted_value)  # Call callback with evicted key and value
            self.cache[key] = value

    def evict(self, key):
        if key in self.cache:
            evicted_key = key
            evicted_value = self.cache.pop(key)
            if self.eviction_callback:
                self.eviction_callback(evicted_key, evicted_value)  # Call callback with evicted key and value
            return True
        return False  # Key not found