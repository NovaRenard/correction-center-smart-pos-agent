"""Interactive local CRM WebSocket mock for Smart POS Agent development."""

from __future__ import annotations

import asyncio
import json
import shlex
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from websockets.asyncio.server import ServerConnection, serve


def _command(
    message_type: str, payload: dict[str, Any], operation_id: str | None = None
) -> dict[str, Any]:
    return {
        "type": message_type,
        "commandId": str(uuid4()),
        "operationId": operation_id,
        "payload": payload,
    }


@dataclass
class MockCrmServer:
    clients: set[ServerConnection] = field(default_factory=set)

    async def handler(self, websocket: ServerConnection) -> None:
        self.clients.add(websocket)
        authorization = websocket.request.headers.get("Authorization", "<not provided>")
        auth_status = "present" if authorization != "<not provided>" else "missing"
        print(f"Agent connected; Authorization header: {auth_status}")
        try:
            async for message in websocket:
                print("<-", message)
        finally:
            self.clients.discard(websocket)
            print("Agent disconnected")

    async def broadcast(self, message: dict[str, Any]) -> None:
        if not self.clients:
            print("No connected agents.")
            return
        text = json.dumps(message, ensure_ascii=False)
        for client in tuple(self.clients):
            await client.send(text)
        print("->", text)

    async def console(self) -> None:
        print(
            "Commands: device | payment <amount> | "
            "refund <amount> <qr|card|alaqan> <transactionId> | quit"
        )
        while True:
            line = await asyncio.to_thread(input, "mock-crm> ")
            parts = shlex.split(line)
            if not parts:
                continue
            if parts[0] in {"quit", "exit"}:
                return
            try:
                if parts[0] == "device" and len(parts) == 1:
                    await self.broadcast(_command("device.check", {}))
                elif parts[0] == "payment" and len(parts) == 2:
                    amount = int(parts[1])
                    await self.broadcast(
                        _command(
                            "payment.start", {"amount": amount, "ownCheque": False}, str(uuid4())
                        )
                    )
                elif parts[0] == "refund" and len(parts) == 4:
                    amount = int(parts[1])
                    await self.broadcast(
                        _command(
                            "refund.start",
                            {
                                "amount": amount,
                                "method": parts[2],
                                "transactionId": parts[3],
                                "ownCheque": False,
                            },
                            str(uuid4()),
                        )
                    )
                else:
                    print("Invalid command.")
            except ValueError:
                print("Amount must be an integer number of tenge.")


async def main() -> None:
    mock = MockCrmServer()
    async with serve(mock.handler, "127.0.0.1", 8765):
        print("Mock CRM listening at ws://127.0.0.1:8765")
        await mock.console()


if __name__ == "__main__":
    asyncio.run(main())
