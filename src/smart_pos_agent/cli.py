from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

import typer
from pydantic import ValidationError

from .application import Application
from .config import Settings
from .version import __version__

app = typer.Typer(help="Локальный агент официального Kaspi Smart POS API.", no_args_is_help=True)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Показать версию."
        ),
    ] = False,
) -> None:
    """Команды диагностики и обслуживания Smart POS Agent."""


def _build_application() -> Application:
    try:
        return Application(Settings())  # type: ignore[call-arg]
    except ValidationError as exc:
        typer.echo(f"Ошибка конфигурации: {exc}", err=True)
        raise typer.Exit(code=2) from exc


def _run(action: Callable[[Application], Awaitable[Any]]) -> None:
    async def runner() -> Any:
        application = _build_application()
        try:
            return await action(application)
        finally:
            await application.close()

    result = asyncio.run(runner())
    if result is not None:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


@app.command()
def doctor() -> None:
    """Проверить конфигурацию, хранилище, POS и CRM без вывода секретов."""
    _run(lambda application: application.doctor())


@app.command()
def register() -> None:
    """Запросить регистрацию на терминале и сохранить полученные токены."""
    typer.echo("Разрешите регистрацию клиента на экране Smart POS. Токены не будут показаны.")
    _run(lambda application: application.register())
    typer.echo("Smart POS зарегистрирован; токены сохранены в защищённом хранилище.")


@app.command("device-info")
def device_info() -> None:
    """Получить posNum, serialNum и terminalId."""
    _run(lambda application: application.device_info())


@app.command()
def run() -> None:
    """Запустить постоянное WebSocket-подключение к CRM."""
    _run(lambda application: application.run())


def _confirm_real_operation(yes: bool, kind: str, amount: int) -> None:
    if yes:
        return
    confirmed = typer.confirm(f"Выполнить реальную {kind} на {amount} ₸ на физическом терминале?")
    if not confirmed:
        raise typer.Abort()


@app.command("test-payment")
def test_payment(
    amount: int = typer.Option(..., min=1, help="Целая сумма в тенге."),
    yes: bool = typer.Option(False, "--yes", help="Не запрашивать интерактивное подтверждение."),
) -> None:
    """Провести настоящую тестовую оплату на терминале."""
    _confirm_real_operation(yes, "тестовую оплату", amount)
    _run(lambda application: application.test_payment(amount))


@app.command("test-refund")
def test_refund(
    amount: int = typer.Option(..., min=1, help="Целая сумма в тенге."),
    method: str = typer.Option(..., help="qr, card или alaqan."),
    transaction_id: str = typer.Option(..., "--transaction-id"),
    yes: bool = typer.Option(False, "--yes", help="Не запрашивать интерактивное подтверждение."),
) -> None:
    """Провести настоящий возврат тем же методом, что и платёж."""
    if method not in {"qr", "card", "alaqan"}:
        raise typer.BadParameter("Допустимы только qr, card или alaqan", param_hint="--method")
    _confirm_real_operation(yes, "тестовый возврат", amount)
    _run(lambda application: application.test_refund(amount, method, transaction_id))


@app.command("show-status")
def show_status() -> None:
    """Показать локально сохранённое состояние без секретов."""
    _run(lambda application: asyncio.sleep(0, result=application.show_status()))


@app.command("clear-smart-pos-credentials")
def clear_smart_pos_credentials() -> None:
    """Удалить только сохранённые access/refresh токены Smart POS."""
    application = _build_application()
    try:
        application.clear_smart_pos_credentials()
    finally:
        asyncio.run(application.close())
    typer.echo("Учётные данные Smart POS удалены.")
