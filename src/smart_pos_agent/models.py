from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

OperationType = Literal["payment", "refund"]


@dataclass(frozen=True, slots=True)
class OperationRecord:
    id: str
    crm_operation_id: str | None
    command_id: str
    type: OperationType
    requested_amount: int
    requested_method: str | None
    requested_transaction_id: str | None
    process_id: str | None
    status: str
    sub_status: str | None
    transaction_id: str | None
    payment_method: str | None
    terminal_id: str | None
    response_json: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class StoredCommand:
    command_id: str
    operation_id: str | None
    response: dict[str, Any]
