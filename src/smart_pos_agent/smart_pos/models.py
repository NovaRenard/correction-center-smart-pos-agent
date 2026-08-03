from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status_code: int = Field(alias="statusCode")
    data: Any = None
    error_text: str | None = Field(default=None, alias="errorText")


class Tokens(BaseModel):
    access_token: str = Field(alias="accessToken", min_length=1)
    refresh_token: str = Field(alias="refreshToken", min_length=1)
    expiration_date: datetime = Field(alias="expirationDate")

    @field_validator("expiration_date", mode="before")
    @classmethod
    def parse_kaspi_datetime(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.replace(" ", "T")
        return value


class DeviceInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    pos_num: str | None = Field(default=None, alias="posNum")
    serial_num: str | None = Field(default=None, alias="serialNum")
    terminal_id: str | None = Field(default=None, alias="terminalId")


class OperationStart(BaseModel):
    model_config = ConfigDict(extra="allow")

    process_id: str = Field(alias="processId", min_length=1)
    status: str
    sub_status: str | None = Field(default=None, alias="subStatus")


class OperationResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    process_id: str | None = Field(default=None, alias="processId")
    status: str
    sub_status: str | None = Field(default=None, alias="subStatus")
    transaction_id: str | None = Field(default=None, alias="transactionId")
    order_number: str | None = Field(default=None, alias="orderNumber")
    rrn: str | None = None
    method: str | None = None
    terminal_id: str | None = Field(default=None, alias="terminalId")
    cheque_info: dict[str, Any] | None = Field(default=None, alias="chequeInfo")
