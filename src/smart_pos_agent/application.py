from __future__ import annotations

import logging
from typing import Any, cast
from uuid import uuid4

from .config import Settings
from .crm.client import CrmClient
from .events import StatusObserver, notify
from .logging_config import configure_logging
from .operations.manager import OperationManager
from .smart_pos.client import SmartPosClient
from .smart_pos.exceptions import AuthenticationError, SmartPosError
from .smart_pos.service import SmartPosService
from .storage.database import Database
from .storage.operation_repository import OperationRepository
from .storage.secret_store import DevelopmentFileSecretStore, KeyringSecretStore, SecretStore

logger = logging.getLogger(__name__)


class Application:
    def __init__(
        self,
        settings: Settings,
        secret_store: SecretStore | None = None,
        status_observer: StatusObserver | None = None,
    ) -> None:
        self.settings = settings
        configure_logging(
            settings.resolved_data_directory / "logs", settings.log_level, settings.agent_id
        )
        self.secret_store = secret_store or self._default_secret_store()
        self.status_observer = status_observer
        self.database = Database(settings.resolved_data_directory / "agent.sqlite3")
        self.database.initialize()
        self.repository = OperationRepository(self.database)
        self.smart_pos_client = SmartPosClient(settings, self.secret_store)
        self.smart_pos = SmartPosService(self.smart_pos_client)
        self.operations = OperationManager(
            settings, self.repository, self.smart_pos, status_observer=status_observer
        )
        self.crm = CrmClient(
            settings, self.secret_store, self.operations, status_observer=status_observer
        )

    def _default_secret_store(self) -> SecretStore:
        if self.settings.development_mode:
            return DevelopmentFileSecretStore(
                self.settings.resolved_data_directory / "secrets.json"
            )
        return KeyringSecretStore()

    async def close(self) -> None:
        await self.crm.aclose()
        await self.smart_pos_client.aclose()
        self.database.close()

    async def doctor(self) -> dict[str, Any]:
        notify(self.status_observer, "terminal.checking", {})
        checks: dict[str, Any] = {
            "configuration": "ok",
            "secretStore": "ok" if self.secret_store.is_available() else "unavailable",
        }
        try:
            info, _ = await self.smart_pos.device_info(refresh=True)
            checks["smartPos"] = {
                "status": "reachable",
                "terminalId": info.terminal_id,
                "serialNumber": info.serial_num,
                "posNum": info.pos_num,
            }
            notify(self.status_observer, "terminal.ready", checks["smartPos"])
        except AuthenticationError as exc:
            logger.warning("doctor_smart_pos_unauthorized class=%s", exc.__class__.__name__)
            checks["smartPos"] = {"status": "unauthorized", "error": exc.__class__.__name__}
            notify(self.status_observer, "terminal.unauthorized", checks["smartPos"])
        except (SmartPosError, ValueError) as exc:
            logger.warning("doctor_smart_pos_failed class=%s", exc.__class__.__name__)
            checks["smartPos"] = {"status": "unreachable", "error": exc.__class__.__name__}
            notify(self.status_observer, "terminal.unavailable", checks["smartPos"])
        try:
            notify(self.status_observer, "crm.connecting", {})
            await self.crm.check_connection()
            checks["crm"] = "reachable"
            notify(self.status_observer, "crm.connected", {})
        except ConnectionError as exc:
            logger.warning("doctor_crm_failed class=%s", exc.__class__.__name__)
            checks["crm"] = "unreachable"
            notify(self.status_observer, "crm.disconnected", {"error": exc.__class__.__name__})
        return checks

    async def register(self) -> None:
        notify(self.status_observer, "terminal.registration_started", {})
        await self.smart_pos_client.register()
        notify(self.status_observer, "terminal.registration_completed", {})

    async def device_info(self) -> dict[str, Any]:
        notify(self.status_observer, "terminal.checking", {})
        try:
            info, _ = await self.smart_pos.device_info(refresh=True)
        except AuthenticationError as exc:
            notify(self.status_observer, "terminal.unauthorized", {"error": exc.__class__.__name__})
            raise
        except (SmartPosError, ValueError) as exc:
            notify(self.status_observer, "terminal.unavailable", {"error": exc.__class__.__name__})
            raise
        result = info.model_dump(by_alias=True, exclude_none=True)
        notify(self.status_observer, "terminal.ready", result)
        return result

    async def run(self) -> None:
        await self.crm.run()

    async def test_payment(self, amount: int) -> dict[str, Any]:
        from .crm.commands import PaymentPayload, PaymentStartCommand

        command = PaymentStartCommand(
            type="payment.start",
            commandId=f"cli-payment-{uuid4()}",
            operationId=f"cli-payment-{uuid4()}",
            payload=PaymentPayload(amount=amount),
        )
        return await self.operations.handle_payment(command)

    async def test_refund(self, amount: int, method: str, transaction_id: str) -> dict[str, Any]:
        from .crm.commands import RefundMethod, RefundPayload, RefundStartCommand

        if method not in {"qr", "card", "alaqan"}:
            raise ValueError("Refund method must be qr, card or alaqan")
        valid_method = cast(RefundMethod, method)

        command = RefundStartCommand(
            type="refund.start",
            commandId=f"cli-refund-{uuid4()}",
            operationId=f"cli-refund-{uuid4()}",
            payload=RefundPayload(amount=amount, method=valid_method, transactionId=transaction_id),
        )
        return await self.operations.handle_refund(command)

    def show_status(self) -> dict[str, Any]:
        active = self.repository.get_active_operation()
        return {
            "activeOperation": self._operation_summary(active) if active else None,
            "credentialsRegistered": self.smart_pos_client.has_credentials(),
        }

    def clear_smart_pos_credentials(self) -> None:
        self.smart_pos_client.clear_credentials()

    @staticmethod
    def _operation_summary(operation: Any) -> dict[str, Any]:
        return {
            "operationId": operation.crm_operation_id,
            "commandId": operation.command_id,
            "processId": operation.process_id,
            "status": operation.status,
            "subStatus": operation.sub_status,
        }
