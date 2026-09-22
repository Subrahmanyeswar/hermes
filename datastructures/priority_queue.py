import heapq

class MinMaxPriorityQueue:
    def __init__(self):
        self.min_heap = []  # Stores (-priority, item) for min-heap
        self.max_heap = []  # Stores (priority, item) for max-heap
        self.removed = {}   # Tracks items to be removed (item: count)

    def push(self, item, priority):
        heapq.heappush(self.min_heap, (-priority, item))
        heapq.heappush(self.max_heap, (priority, item))
        if item not in self.removed:
            self.removed[item] = 0

    def pop_min(self):
        while self.min_heap:
            neg_priority, item = self.min_heap[0]
            priority = -neg_priority
            if item in self.removed and self.removed[item] > 0:
                heapq.heappop(self.min_heap)
                self.removed[item] -= 1
                if self.removed[item] == 0:
                    del self.removed[item]
            else:
                heapq.heappop(self.min_heap)
                if item in self.removed:
                    self.removed[item] -= 1
                    if self.removed[item] == 0:
                        del self.removed[item]
                return item, priority
        raise Exception("Min heap is empty")

    def pop_max(self):
        while self.max_heap:
            priority, item = self.max_heap[0]
            if item in self.removed and self.removed[item] > 0:
                heapq.heappop(self.max_heap)
                self.removed[item] -= 1
                if self.removed[item] == 0:
                    del self.removed[item]
            else:
                heapq.heappop(self.max_heap)
                if item in self.removed:
                    self.removed[item] -= 1
                    if self.removed[item] == 0:
                        del self.removed[item]
                return item, priority
        raise Exception("Max heap is empty")