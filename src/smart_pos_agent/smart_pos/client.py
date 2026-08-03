from __future__ import annotations

import logging
from typing import Any, TypeVar, cast

import httpx
from pydantic import BaseModel, ValidationError

from ..config import Settings, SmartPosTlsMode
from ..constants import TOKEN_REFRESH_SKEW_SECONDS
from ..logging_config import redact_value
from ..storage.secret_store import SecretStore
from .auth import token_is_due_for_refresh
from .exceptions import (
    AuthenticationError,
    SmartPosApiError,
    SmartPosHttpError,
    SmartPosTransportError,
    TerminalBusyError,
    ValidationApiError,
)
from .models import ApiResponse, DeviceInfo, OperationResult, OperationStart, Tokens

logger = logging.getLogger(__name__)
ModelT = TypeVar("ModelT", bound=BaseModel)

_ACCESS = "smart_pos_access_token"
_REFRESH = "smart_pos_refresh_token"
_EXPIRY = "smart_pos_expiration_date"


class SmartPosClient:
    """Async client for only the documented HTTPS Smart POS v2 API."""

    def __init__(
        self,
        settings: Settings,
        secret_store: SecretStore,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.secret_store = secret_store
        verify: bool | str = True
        if settings.smart_pos_tls_mode is SmartPosTlsMode.CUSTOM_CA:
            verify = str(settings.smart_pos_ca_bundle)
        elif settings.smart_pos_tls_mode is SmartPosTlsMode.IP_INSECURE:
            verify = False
            logger.warning("smart_pos_tls_ip_insecure_enabled")
        self._owns_client = http_client is None
        self.http = http_client or httpx.AsyncClient(
            base_url=settings.smart_pos_base_url,
            verify=verify,
            timeout=settings.smart_pos_request_timeout_seconds,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self.http.aclose()

    def has_credentials(self) -> bool:
        return self._tokens() is not None

    async def register(self) -> Tokens:
        raw = await self._request("/register", params={"name": self.settings.smart_pos_client_name})
        tokens = self._validated_data(raw, Tokens)
        self._save_tokens(tokens)
        logger.info("smart_pos_registered")
        return tokens

    async def refresh_tokens(self) -> Tokens:
        tokens = self._tokens()
        if tokens is None:
            raise AuthenticationError(401, "Smart POS credentials are not registered")
        raw = await self._request(
            "/revoke",
            params={
                "name": self.settings.smart_pos_client_name,
                "refreshToken": tokens.refresh_token,
            },
        )
        refreshed = self._validated_data(raw, Tokens)
        self._save_tokens(refreshed)
        logger.info("smart_pos_token_refreshed")
        return refreshed

    async def device_info(self) -> tuple[DeviceInfo, dict[str, Any]]:
        raw = await self._authenticated_request("/deviceinfo")
        return self._validated_data(raw, DeviceInfo), self._redacted_raw(raw)

    async def start_payment(
        self, amount: int, own_cheque: bool = False
    ) -> tuple[OperationStart, dict[str, Any]]:
        raw = await self._authenticated_request(
            "/payment", params={"amount": amount, "owncheque": str(own_cheque).lower()}
        )
        return self._validated_data(raw, OperationStart), self._redacted_raw(raw)

    async def start_refund(
        self, amount: int, method: str, transaction_id: str, own_cheque: bool = False
    ) -> tuple[OperationStart, dict[str, Any]]:
        raw = await self._authenticated_request(
            "/refund",
            params={
                "amount": amount,
                "method": method,
                "transactionId": transaction_id,
                "owncheque": str(own_cheque).lower(),
            },
        )
        return self._validated_data(raw, OperationStart), self._redacted_raw(raw)

    async def status(
        self, process_id: str, terminal_id: str
    ) -> tuple[OperationResult, dict[str, Any]]:
        raw = await self._authenticated_request(
            "/status", params={"processId": process_id}, terminal_id=terminal_id
        )
        return self._validated_data(raw, OperationResult), self._redacted_raw(raw)

    async def actualize(self, process_id: str) -> tuple[OperationResult, dict[str, Any]]:
        raw = await self._authenticated_request("/actualize", params={"processId": process_id})
        return self._validated_data(raw, OperationResult), self._redacted_raw(raw)

    async def _authenticated_request(
        self, path: str, *, params: dict[str, Any] | None = None, terminal_id: str | None = None
    ) -> dict[str, Any]:
        tokens = self._tokens()
        if tokens is None:
            raise AuthenticationError(401, "Smart POS credentials are not registered")
        if token_is_due_for_refresh(tokens, TOKEN_REFRESH_SKEW_SECONDS):
            tokens = await self.refresh_tokens()
        try:
            return await self._request_with_access(
                path, params=params, access_token=tokens.access_token, terminal_id=terminal_id
            )
        except AuthenticationError as exc:
            if exc.status_code not in {401, 403}:
                raise
            refreshed = await self.refresh_tokens()
            return await self._request_with_access(
                path, params=params, access_token=refreshed.access_token, terminal_id=terminal_id
            )

    async def _request_with_access(
        self,
        path: str,
        *,
        params: dict[str, Any] | None,
        access_token: str,
        terminal_id: str | None,
    ) -> dict[str, Any]:
        headers = {"accesstoken": access_token}
        if terminal_id:
            headers["terminalId"] = terminal_id
        return await self._request(path, params=params, headers=headers)

    async def _request(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self.http.get(path, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            logger.warning("smart_pos_timeout endpoint=%s", path)
            raise SmartPosTransportError(f"Smart POS timeout at {path}") from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "smart_pos_transport_error endpoint=%s class=%s", path, exc.__class__.__name__
            )
            raise SmartPosTransportError(f"Smart POS transport error at {path}") from exc
        if response.status_code in {401, 403}:
            raise AuthenticationError(
                response.status_code, f"Smart POS HTTP {response.status_code}"
            )
        if response.status_code >= 400:
            raise SmartPosHttpError(response.status_code, f"Smart POS HTTP {response.status_code}")
        try:
            raw = response.json()
        except ValueError as exc:
            raise SmartPosHttpError(
                response.status_code, "Smart POS returned non-JSON response"
            ) from exc
        if not isinstance(raw, dict):
            raise SmartPosHttpError(response.status_code, "Smart POS returned malformed JSON")
        envelope = self._validated_envelope(raw)
        if envelope.status_code != 0:
            self._raise_api_error(envelope.status_code, envelope.error_text)
        return raw

    @staticmethod
    def _validated_envelope(raw: dict[str, Any]) -> ApiResponse:
        try:
            return ApiResponse.model_validate(raw)
        except ValidationError as exc:
            raise SmartPosHttpError(200, "Smart POS response has invalid envelope") from exc

    @staticmethod
    def _validated_data(raw: dict[str, Any], model: type[ModelT]) -> ModelT:
        try:
            data = raw.get("data")
            if not isinstance(data, dict):
                raise ValueError("data is missing")
            return model.model_validate(data)
        except (ValidationError, ValueError) as exc:
            raise SmartPosHttpError(
                200, f"Smart POS response has invalid {model.__name__}"
            ) from exc

    @staticmethod
    def _redacted_raw(raw: dict[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], redact_value(raw))

    @staticmethod
    def _raise_api_error(status_code: int, error_text: str | None) -> None:
        if status_code in {100, 101, 105, 106, 108, 999}:
            raise ValidationApiError(status_code, error_text)
        if status_code == 107:
            raise TerminalBusyError(status_code, error_text)
        raise SmartPosApiError(status_code, error_text)

    def _tokens(self) -> Tokens | None:
        access_token = self.secret_store.get(_ACCESS)
        refresh_token = self.secret_store.get(_REFRESH)
        expiration_date = self.secret_store.get(_EXPIRY)
        if not access_token or not refresh_token or not expiration_date:
            return None
        try:
            return Tokens.model_validate(
                {
                    "accessToken": access_token,
                    "refreshToken": refresh_token,
                    "expirationDate": expiration_date,
                }
            )
        except ValidationError:
            logger.error("smart_pos_stored_credentials_invalid")
            return None

    def _save_tokens(self, tokens: Tokens) -> None:
        self.secret_store.set(_ACCESS, tokens.access_token)
        self.secret_store.set(_REFRESH, tokens.refresh_token)
        self.secret_store.set(_EXPIRY, tokens.expiration_date.isoformat())

    def clear_credentials(self) -> None:
        for key in (_ACCESS, _REFRESH, _EXPIRY):
            self.secret_store.delete(key)
