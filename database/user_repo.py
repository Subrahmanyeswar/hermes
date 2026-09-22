import sqlite3
from typing import Optional, Tuple

class UserRepo:
    """Repository class for user database operations."""

    def __init__(self, db_path: str = 'database.db'):
        """Initialize the user repository with a database path."""
        self.db_path = db_path

    def get_user_by_id(self, user_id: int) -> Optional[Tuple]:
        """Retrieve a user by their ID using a parameterized query to prevent SQL injection."""
        conn = None
        cursor = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            # Using parameterized query to securely handle user ID
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            user_data = cursor.fetchone()
            return user_data
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return None
        finally:
            if conn:
                conn.close()

# Example usage if this module is run directly
if __name__ == "__main__":
    repo = UserRepo()
    user = repo.get_user_by_id(1)
    print(user)