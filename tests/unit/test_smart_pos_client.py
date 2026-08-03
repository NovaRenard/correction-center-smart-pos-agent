from __future__ import annotations

import httpx
import pytest
import respx

from smart_pos_agent.config import Settings
from smart_pos_agent.smart_pos.client import SmartPosClient
from smart_pos_agent.storage.secret_store import InMemorySecretStore


def envelope(data: dict[str, object]) -> dict[str, object]:
    return {"statusCode": 0, "data": data}


def stored_tokens(store: InMemorySecretStore) -> None:
    store.set("smart_pos_access_token", "old-access")
    store.set("smart_pos_refresh_token", "old-refresh")
    store.set("smart_pos_expiration_date", "2035-01-01T00:00:00+00:00")


@pytest.mark.asyncio
@respx.mock
async def test_parses_successful_registration(
    settings: Settings, secrets: InMemorySecretStore
) -> None:
    route = respx.get(f"{settings.smart_pos_base_url}/register").mock(
        return_value=httpx.Response(
            200,
            json=envelope(
                {
                    "accessToken": "access",
                    "refreshToken": "refresh",
                    "expirationDate": "2035-01-01 00:00:00",
                }
            ),
        )
    )
    async with httpx.AsyncClient(base_url=settings.smart_pos_base_url) as http:
        client = SmartPosClient(settings, secrets, http)
        tokens = await client.register()
    assert tokens.access_token == "access"
    assert secrets.get("smart_pos_refresh_token") == "refresh"
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_refreshes_token(settings: Settings, secrets: InMemorySecretStore) -> None:
    stored_tokens(secrets)
    respx.get(f"{settings.smart_pos_base_url}/revoke").mock(
        return_value=httpx.Response(
            200,
            json=envelope(
                {
                    "accessToken": "new-access",
                    "refreshToken": "new-refresh",
                    "expirationDate": "2035-01-01 00:00:00",
                }
            ),
        )
    )
    async with httpx.AsyncClient(base_url=settings.smart_pos_base_url) as http:
        tokens = await SmartPosClient(settings, secrets, http).refresh_tokens()
    assert tokens.access_token == "new-access"
    assert secrets.get("smart_pos_access_token") == "new-access"


@pytest.mark.asyncio
@respx.mock
async def test_retries_device_info_once_after_403(
    settings: Settings, secrets: InMemorySecretStore
) -> None:
    stored_tokens(secrets)
    calls = 0

    def device_response(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            assert request.headers["accesstoken"] == "old-access"
            return httpx.Response(403)
        assert request.headers["accesstoken"] == "new-access"
        return httpx.Response(
            200, json=envelope({"posNum": "1", "serialNum": "s", "terminalId": "t"})
        )

    respx.get(f"{settings.smart_pos_base_url}/deviceinfo").mock(side_effect=device_response)
    respx.get(f"{settings.smart_pos_base_url}/revoke").mock(
        return_value=httpx.Response(
            200,
            json=envelope(
                {
                    "accessToken": "new-access",
                    "refreshToken": "new-refresh",
                    "expirationDate": "2035-01-01 00:00:00",
                }
            ),
        )
    )
    async with httpx.AsyncClient(base_url=settings.smart_pos_base_url) as http:
        info, _ = await SmartPosClient(settings, secrets, http).device_info()
    assert calls == 2
    assert info.terminal_id == "t"


@pytest.mark.asyncio
@respx.mock
async def test_deviceinfo_and_start_payment(
    settings: Settings, secrets: InMemorySecretStore
) -> None:
    stored_tokens(secrets)
    respx.get(f"{settings.smart_pos_base_url}/deviceinfo").mock(
        return_value=httpx.Response(
            200, json=envelope({"posNum": "1", "serialNum": "s", "terminalId": "t"})
        )
    )
    payment = respx.get(f"{settings.smart_pos_base_url}/payment").mock(
        return_value=httpx.Response(200, json=envelope({"processId": "p-1", "status": "wait"}))
    )
    async with httpx.AsyncClient(base_url=settings.smart_pos_base_url) as http:
        client = SmartPosClient(settings, secrets, http)
        info, _ = await client.device_info()
        start, _ = await client.start_payment(10)
    assert info.pos_num == "1"
    assert start.process_id == "p-1"
    assert payment.called


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("method", ["qr", "card"])
async def test_starts_qr_and_card_refund(
    settings: Settings, secrets: InMemorySecretStore, method: str
) -> None:
    stored_tokens(secrets)
    route = respx.get(f"{settings.smart_pos_base_url}/refund").mock(
        return_value=httpx.Response(200, json=envelope({"processId": "refund-1", "status": "wait"}))
    )
    async with httpx.AsyncClient(base_url=settings.smart_pos_base_url) as http:
        start, _ = await SmartPosClient(settings, secrets, http).start_refund(10, method, "tx-1")
    assert start.process_id == "refund-1"
    assert route.called
