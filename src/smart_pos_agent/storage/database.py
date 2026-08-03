from __future__ import annotations

import sqlite3
from pathlib import Path


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")

    def initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS agent_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS operations (
                id TEXT PRIMARY KEY,
                crm_operation_id TEXT,
                command_id TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL CHECK(type IN ('payment', 'refund')),
                requested_amount INTEGER NOT NULL CHECK(requested_amount > 0),
                requested_method TEXT,
                requested_transaction_id TEXT,
                process_id TEXT,
                status TEXT NOT NULL,
                sub_status TEXT,
                transaction_id TEXT,
                payment_method TEXT,
                terminal_id TEXT,
                response_json TEXT,
                error_code TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS processed_commands (
                command_id TEXT PRIMARY KEY,
                operation_id TEXT,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(operation_id) REFERENCES operations(id)
            );
            CREATE INDEX IF NOT EXISTS idx_operations_active ON operations(status, created_at);
            """
        )

    def close(self) -> None:
        self.connection.close()
