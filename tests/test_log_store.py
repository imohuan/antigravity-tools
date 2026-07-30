"""LogStore schema migration regression tests."""

import os
import sqlite3
import tempfile
import threading
import unittest

from src.modules.log_store import LogStore


class TestLogStoreSchemaMigration(unittest.TestCase):
    def test_existing_migration_columns_are_not_added_again(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "request_logs.db")
            connection = sqlite3.connect(db_path)
            connection.execute(
                """
                CREATE TABLE request_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    date TEXT NOT NULL,
                    hour INTEGER NOT NULL DEFAULT 0,
                    main_key_id TEXT DEFAULT '',
                    main_key_label TEXT DEFAULT '',
                    model TEXT DEFAULT '',
                    status TEXT DEFAULT '',
                    prompt_tokens INTEGER DEFAULT 0,
                    completion_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    credit REAL DEFAULT 0.0,
                    duration_ms INTEGER DEFAULT 0,
                    request_path TEXT DEFAULT '',
                    key_mode TEXT DEFAULT '',
                    error TEXT DEFAULT '',
                    first_token_ms INTEGER DEFAULT 0,
                    attempt INTEGER DEFAULT 1
                )
                """
            )
            connection.commit()
            connection.close()

            store = LogStore(db_path)
            self.assertIsNotNone(store.conn)
            store.conn.close()

    def test_concurrent_first_access_initializes_schema_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "request_logs.db")
            store = LogStore(db_path)
            errors = []
            barrier = threading.Barrier(8)

            def access_connection():
                try:
                    barrier.wait()
                    store.conn.execute("SELECT COUNT(*) FROM request_logs")
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=access_connection) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            store.conn.close()


if __name__ == "__main__":
    unittest.main()