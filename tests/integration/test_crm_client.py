from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection, serve

from smart_pos_agent.config import Settings
from smart_pos_agent.crm.client import CrmClient
from smart_pos_agent.crm.reconnect import ExponentialBackoff
from smart_pos_agent.smart_pos.models import DeviceInfo
from smart_pos_agent.storage.secret_store import InMemorySecretStore


class DummySmartPos:
    async def device_info(self, *, refresh: bool = False) -> tuple[DeviceInfo, dict[str, Any]]:
        info = DeviceInfo(posNum="pos", serialNum="serial", terminalId="terminal")
        return info, {"statusCode": 0, "data": info.model_dump(by_alias=True)}


class DummyOperations:
    def __init__(self) -> None:
        self.smart_pos = DummySmartPos()
        self.event_sink: Any = None

    def set_event_sink(self, event_sink: Any) -> None:
        self.event_sink = event_sink

    def active_operation_id(self) -> None:
        return None

    async def resume_incomplete(self) -> None:
        return None

    async def handle_device_check(self, command: Any) -> None:
        return None

    async def handle_payment(self, command: Any) -> None:
        return None

    async def handle_refund(self, command: Any) -> None:
        return None


@pytest.mark.asyncio
async def test_websocket_reconnects_and_sends_hello(settings: Settings) -> None:
    connected: list[str] = []
    complete = asyncio.Event()
    crm: CrmClient | None = None

    async def handler(websocket: ServerConnection) -> None:
        nonlocal crm
        connected.append(websocket.request.headers.get("Authorization", ""))
        raw = await websocket.recv()
        assert json.loads(raw)["type"] == "agent.hello"
        if len(connected) == 1:
            await websocket.close()
        else:
            assert crm is not None
            crm.stop()
            complete.set()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        reconnect_settings = settings.model_copy(update={"crm_ws_url": f"ws://127.0.0.1:{port}"})
        crm = CrmClient(
            reconnect_settings,
            InMemorySecretStore({"crm_agent_token": "test-token"}),
            DummyOperations(),  # type: ignore[arg-type]
        )
        await asyncio.wait_for(crm.run(), timeout=1)
    assert complete.is_set()
    assert connected == ["Bearer test-token", "Bearer test-token"]


@pytest.mark.asyncio
async def test_heartbeat_and_unknown_command_protocol_error(settings: Settings) -> None:
    class Socket:
        def __init__(self) -> None:
            self.messages: list[str] = []

        async def send(self, message: str) -> None:
            self.messages.append(message)

    socket = Socket()
    heartbeat_settings = settings.model_copy(update={"heartbeat_interval_seconds": 0.001})
    crm = CrmClient(
        heartbeat_settings,
        InMemorySecretStore({"crm_agent_token": "test-token"}),
        DummyOperations(),  # type: ignore[arg-type]
    )
    crm._socket = socket  # type: ignore[assignment]
    task = asyncio.create_task(crm._heartbeat_loop())
    await asyncio.sleep(0.03)
    crm._socket = None
    await task
    crm._socket = socket  # type: ignore[assignment]
    await crm._handle_message('{"type":"not.real","commandId":"x","payload":{}}')
    event_types = [json.loads(message)["type"] for message in socket.messages]
    assert "agent.heartbeat" in event_types
    assert "protocol.error" in event_types


def test_backoff_has_jitter_and_cap() -> None:
    backoff = ExponentialBackoff(1, 4)
    values = [backoff.next_delay() for _ in range(5)]
    assert all(0.8 <= value <= 4.8 for value in values)
