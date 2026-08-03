"""Qt-facing controller that owns one core Application on a private asyncio loop."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable, Mapping
from concurrent.futures import Future
from typing import Any

from PySide6.QtCore import QObject, Signal

from ..application import Application
from ..config import Settings
from ..storage.secret_store import SecretStore
from .state import AgentStateStore, AgentUiState, LifecycleStatus

logger = logging.getLogger(__name__)
SettingsFactory = Callable[[], Settings]


class AgentRuntime(QObject):
    """Runs the core outside the Qt event loop and exposes safe UI commands.

    A desktop process has exactly one runtime and it creates exactly one Application,
    keeping SQLite and the terminal-operation lock in the same background thread.
    """

    state_changed = Signal(object)
    core_event = Signal(str, object)
    action_completed = Signal(str, object)
    action_failed = Signal(str, str)
    stopped = Signal()

    def __init__(self, settings_factory: SettingsFactory, secret_store: SecretStore) -> None:
        super().__init__()
        self._settings_factory = settings_factory
        self._secret_store = secret_store
        self._state_store = AgentStateStore(AgentUiState())
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._application: Application | None = None
        self._crm_url = ""
        self._lock = threading.RLock()
        self._loop_ready = threading.Event()

    @property
    def state(self) -> AgentUiState:
        return self._state_store.snapshot()

    @property
    def crm_url(self) -> str:
        return self._crm_url

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._loop_ready.clear()
            self._emit_state(self._state_store.set_lifecycle(LifecycleStatus.STARTING))
            self._thread = threading.Thread(
                target=self._thread_main, name="smart-pos-agent-runtime", daemon=False
            )
            self._thread.start()

    def stop(self) -> None:
        """Request an asynchronous, orderly shutdown without blocking the GUI thread."""
        self._emit_state(self._state_store.set_lifecycle(LifecycleStatus.STOPPING))
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        future = asyncio.run_coroutine_threadsafe(self._stop_application(), loop)
        future.add_done_callback(self._log_stop_failure)

    def check_connections(self) -> Future[Any] | None:
        return self._submit("check_connections", lambda app: app.doctor())

    def register_smart_pos(self) -> Future[Any] | None:
        async def action(application: Application) -> dict[str, Any]:
            await application.register()
            return await application.device_info()

        return self._submit("register_smart_pos", action)

    def get_device_info(self) -> Future[Any] | None:
        return self._submit("get_device_info", lambda app: app.device_info())

    def reconnect_crm(self) -> Future[Any] | None:
        return self._submit("reconnect_crm", lambda app: app.crm.reconnect())

    def get_status(self) -> Future[Any] | None:
        async def action(application: Application) -> dict[str, Any]:
            return application.show_status()

        return self._submit("get_status", action)

    def clear_smart_pos_credentials(self) -> Future[Any] | None:
        async def action(application: Application) -> None:
            application.clear_smart_pos_credentials()

        return self._submit("clear_smart_pos_credentials", action)

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop
        self._loop_ready.set()
        try:
            loop.run_until_complete(self._run_application())
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            with self._lock:
                self._application = None
                self._loop = None
            self._emit_state(self._state_store.set_lifecycle(LifecycleStatus.STOPPED))
            self.stopped.emit()

    async def _run_application(self) -> None:
        application: Application | None = None
        failed = False
        try:
            settings = self._settings_factory()
            self._crm_url = settings.crm_ws_url
            initial = AgentUiState(
                agent_id=settings.agent_id,
                agent_name=settings.agent_name,
                agent_version=settings.agent_version,
                terminal_host=f"{settings.smart_pos_host}:{settings.smart_pos_port}",
            )
            self._state_store = AgentStateStore(initial)
            self._emit_state(self._state_store.set_lifecycle(LifecycleStatus.STARTING))
            application = Application(
                settings, secret_store=self._secret_store, status_observer=self._on_core_event
            )
            with self._lock:
                self._application = application
            self._emit_state(self._state_store.set_lifecycle(LifecycleStatus.RUNNING))
            await application.run()
        except Exception as exc:
            failed = True
            logger.exception("desktop_runtime_failed class=%s", exc.__class__.__name__)
            self._emit_state(self._state_store.set_lifecycle(LifecycleStatus.ERROR, exc))
        finally:
            if application is not None:
                try:
                    await application.close()
                except Exception as exc:  # pragma: no cover - defensive shutdown path
                    logger.exception(
                        "desktop_runtime_close_failed class=%s", exc.__class__.__name__
                    )
                    if not failed:
                        self._emit_state(
                            self._state_store.set_lifecycle(LifecycleStatus.ERROR, exc)
                        )

    async def _stop_application(self) -> None:
        application = self._application
        if application is not None:
            await application.crm.aclose()

    def _submit(
        self, action_name: str, action: Callable[[Application], Awaitable[Any]]
    ) -> Future[Any] | None:
        loop = self._loop
        application = self._application
        if loop is None or application is None or loop.is_closed():
            self.action_failed.emit(action_name, "Агент ещё не запущен.")
            return None

        async def runner() -> Any:
            return await action(application)

        future = asyncio.run_coroutine_threadsafe(runner(), loop)

        def completed(result: Future[Any]) -> None:
            try:
                value = result.result()
            except Exception as exc:
                logger.warning(
                    "desktop_action_failed name=%s class=%s", action_name, exc.__class__.__name__
                )
                self.action_failed.emit(action_name, self._safe_error(exc))
            else:
                self.action_completed.emit(action_name, value)

        future.add_done_callback(completed)
        return future

    def _on_core_event(self, event: str, payload: Mapping[str, Any]) -> None:
        state = self._state_store.apply_core_event(event, payload)
        self._emit_state(state)
        self.core_event.emit(event, dict(payload))

    def _emit_state(self, state: AgentUiState) -> None:
        self.state_changed.emit(state)

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        from .state import redact_ui_error

        return redact_ui_error(exc)

    @staticmethod
    def _log_stop_failure(result: Future[Any]) -> None:
        try:
            result.result()
        except Exception as exc:  # pragma: no cover - shutdown telemetry only
            logger.warning("desktop_runtime_stop_failed class=%s", exc.__class__.__name__)
