import sqlite3

class SQLiteStorage:
    def __init__(self, db_path='symbols.db'):
        self.db_path = db_path

    def connect(self):
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        self._create_table()

    def _create_table(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS symbols (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol_name TEXT,
                symbol_type TEXT,
                file_path TEXT,
                line_number INTEGER
            )
        ''')

    def insert_symbol(self, symbol_name, symbol_type, file_path, line_number):
        self.cursor.execute('''
            INSERT INTO symbols (symbol_name, symbol_type, file_path, line_number)
            VALUES (?, ?, ?, ?)
        ''', (symbol_name, symbol_type, file_path, line_number))
        self.conn.commit()

    def close(self):
        self.conn.close()
