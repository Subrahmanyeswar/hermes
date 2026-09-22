import os
import sqlite3
from queue import Queue
import threading

class DatabaseConnection:
    def __init__(self, db_path):
        self.db_path = db_path
        self.connection = None

    def connect(self):
        try:
            self.connection = sqlite3.connect(self.db_path)
        except sqlite3.Error as e:
            print(f"Database connection error: {e}")
            raise  # Re-raise the specific database error


class QueueWorker:
    def __init__(self, queue):
        self.queue = queue

    def process_task(self):
        task = self.queue.get()
        try:
            db = DatabaseConnection('mydatabase.db')
            db.connect()
            cursor = db.connection.cursor()
            cursor.execute("SELECT * FROM tasks WHERE id=?", (task,))
            results = cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Critical database error: {e}")
            # Handle the error, e.g., log and retry or terminate
            # This prevents silent error swallowing
        except Exception as e:
            print(f"Unexpected error: {e}")
            raise  # Re-raise unexpected errors for proper handling

    def run(self):
        while True:
            self.process_task()

if __name__ == "__main__":
    q = Queue()
    worker = QueueWorker(q)
    t = threading.Thread(target=worker.run)
    t.daemon = True
    t.start()
    # Main thread can add tasks or exit