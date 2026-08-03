from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .models import Tokens


def token_is_due_for_refresh(tokens: Tokens, skew_seconds: int = 300) -> bool:
    expires_at = tokens.expiration_date
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC) + timedelta(seconds=skew_seconds)
