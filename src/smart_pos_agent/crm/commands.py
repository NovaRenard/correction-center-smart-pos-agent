from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

PositiveTenge = Annotated[StrictInt, Field(gt=0)]
type RefundMethod = Literal["qr", "card", "alaqan"]


class CommandBase(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    command_id: str = Field(alias="commandId", min_length=1)
    operation_id: str | None = Field(alias="operationId", default=None)


class DeviceCheckCommand(CommandBase):
    type: Literal["device.check"]
    payload: dict[str, object] = Field(default_factory=dict)


class PaymentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    amount: PositiveTenge
    own_cheque: bool = Field(default=False, alias="ownCheque")


class PaymentStartCommand(CommandBase):
    type: Literal["payment.start"]
    operation_id: str = Field(alias="operationId", min_length=1)
    payload: PaymentPayload


class RefundPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    amount: PositiveTenge
    method: RefundMethod
    transaction_id: str = Field(alias="transactionId", min_length=1)
    own_cheque: bool = Field(default=False, alias="ownCheque")


class RefundStartCommand(CommandBase):
    type: Literal["refund.start"]
    operation_id: str = Field(alias="operationId", min_length=1)
    payload: RefundPayload


type IncomingCommand = DeviceCheckCommand | PaymentStartCommand | RefundStartCommand
