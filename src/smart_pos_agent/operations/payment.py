from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def normalize_reported_amount(cheque_info: dict[str, Any] | None) -> int | None:
    """Normalize a terminal amount without floating point conversion."""
    if not cheque_info or cheque_info.get("amount") is None:
        return None
    try:
        amount = Decimal(str(cheque_info["amount"]))
    except (InvalidOperation, ValueError):
        return None
    if amount != amount.to_integral_value() or amount < 0:
        return None
    return int(amount)
