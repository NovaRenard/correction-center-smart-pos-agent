from __future__ import annotations

import pytest
from pydantic import ValidationError

from smart_pos_agent.crm.protocol import UnknownCommandType, parse_command
from smart_pos_agent.logging_config import redact_value


def test_redacts_all_token_bearing_values() -> None:
    value = redact_value(
        {
            "accessToken": "access-secret",
            "refresh_token": "refresh-secret",
            "Authorization": "Bearer crm-secret",
            "nested": [{"token": "another-secret"}],
        }
    )
    assert value == {
        "accessToken": "[REDACTED]",
        "refresh_token": "[REDACTED]",
        "Authorization": "[REDACTED]",
        "nested": [{"token": "[REDACTED]"}],
    }


def test_unknown_crm_command_does_not_validate_as_known() -> None:
    with pytest.raises(UnknownCommandType):
        parse_command('{"type":"unexpected.command","commandId":"1","payload":{}}')


def test_invalid_command_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_command(
            '{"type":"payment.start","commandId":"1","operationId":"2","payload":{"amount":1.5}}'
        )
