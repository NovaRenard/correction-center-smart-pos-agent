from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from ..constants import ACTIVE_STATUSES
from ..logging_config import json_for_storage
from ..models import OperationRecord, OperationType, StoredCommand
from .database import Database


def utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class OperationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get_command(self, command_id: str) -> StoredCommand | None:
        row = self.database.connection.execute(
            "SELECT command_id, operation_id, response_json "
            "FROM processed_commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        if row is None:
            return None
        return StoredCommand(
            command_id=row["command_id"],
            operation_id=row["operation_id"],
            response=json.loads(row["response_json"]),
        )

    def record_command(
        self, command_id: str, response: dict[str, Any], operation_id: str | None = None
    ) -> None:
        self.database.connection.execute(
            """INSERT OR REPLACE INTO processed_commands(
                command_id, operation_id, response_json, created_at
            ) VALUES (?, ?, ?, ?)""",
            (command_id, operation_id, json_for_storage(response), utc_now().isoformat()),
        )

    def create_operation(
        self,
        *,
        operation_id: str,
        crm_operation_id: str | None,
        command_id: str,
        operation_type: OperationType,
        amount: int,
        method: str | None,
        transaction_id: str | None,
    ) -> OperationRecord:
        now = utc_now()
        self.database.connection.execute(
            """INSERT INTO operations(
                id, crm_operation_id, command_id, type, requested_amount, requested_method,
                requested_transaction_id, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'accepted', ?, ?)""",
            (
                operation_id,
                crm_operation_id,
                command_id,
                operation_type,
                amount,
                method,
                transaction_id,
                now.isoformat(),
                now.isoformat(),
            ),
        )
        return self.get_operation(operation_id)  # type: ignore[return-value]

    def get_operation(self, operation_id: str) -> OperationRecord | None:
        row = self.database.connection.execute(
            "SELECT * FROM operations WHERE id = ?", (operation_id,)
        ).fetchone()
        return self._to_record(row) if row is not None else None

    def get_active_operation(self) -> OperationRecord | None:
        placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
        row = self.database.connection.execute(
            f"SELECT * FROM operations WHERE status IN ({placeholders}) "  # noqa: S608
            "ORDER BY created_at LIMIT 1",
            tuple(ACTIVE_STATUSES),
        ).fetchone()
        return self._to_record(row) if row is not None else None

    def get_incomplete_operations(self) -> list[OperationRecord]:
        placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
        rows = self.database.connection.execute(
            f"SELECT * FROM operations WHERE status IN ({placeholders}) "  # noqa: S608
            "AND process_id IS NOT NULL ORDER BY created_at",
            tuple(ACTIVE_STATUSES),
        ).fetchall()
        return [self._to_record(row) for row in rows]

    def get_operations_without_process(self) -> list[OperationRecord]:
        rows = self.database.connection.execute(
            "SELECT * FROM operations WHERE status = 'accepted' "
            "AND process_id IS NULL ORDER BY created_at"
        ).fetchall()
        return [self._to_record(row) for row in rows]

    def update_operation(self, operation_id: str, **fields: Any) -> OperationRecord:
        allowed = {
            "process_id",
            "status",
            "sub_status",
            "transaction_id",
            "payment_method",
            "terminal_id",
            "response_json",
            "error_code",
            "error_message",
            "completed_at",
        }
        unexpected = set(fields).difference(allowed)
        if unexpected:
            raise ValueError(f"Unsupported operation fields: {sorted(unexpected)}")
        values: dict[str, Any] = dict(fields)
        if "response_json" in values and values["response_json"] is not None:
            values["response_json"] = json_for_storage(values["response_json"])
        if "completed_at" in values and isinstance(values["completed_at"], datetime):
            values["completed_at"] = values["completed_at"].isoformat()
        values["updated_at"] = utc_now().isoformat()
        assignments = ", ".join(f"{key} = ?" for key in values)
        self.database.connection.execute(
            f"UPDATE operations SET {assignments} WHERE id = ?",  # noqa: S608
            (*values.values(), operation_id),
        )
        return self.get_operation(operation_id)  # type: ignore[return-value]

    @staticmethod
    def _to_record(row: Any) -> OperationRecord:
        response_json = json.loads(row["response_json"]) if row["response_json"] else None
        created = _as_utc_datetime(row["created_at"])
        updated = _as_utc_datetime(row["updated_at"])
        if created is None or updated is None:
            raise ValueError("Operation timestamps must be present")
        return OperationRecord(
            id=row["id"],
            crm_operation_id=row["crm_operation_id"],
            command_id=row["command_id"],
            type=row["type"],
            requested_amount=row["requested_amount"],
            requested_method=row["requested_method"],
            requested_transaction_id=row["requested_transaction_id"],
            process_id=row["process_id"],
            status=row["status"],
            sub_status=row["sub_status"],
            transaction_id=row["transaction_id"],
            payment_method=row["payment_method"],
            terminal_id=row["terminal_id"],
            response_json=response_json,
            error_code=row["error_code"],
            error_message=row["error_message"],
            created_at=created,
            updated_at=updated,
            completed_at=_as_utc_datetime(row["completed_at"]),
        )
