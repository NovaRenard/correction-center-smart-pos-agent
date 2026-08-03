# Correction Center Smart POS Agent

Локальный Windows-агент, который связывает облачную `correction-center-crm` с физическим Kaspi Smart POS. CRM остаётся источником истины для учеников, занятий, задолженностей и оплат; агент только выполняет команды терминала и сообщает результат.

Это интеграция **только с официальным локальным Smart POS API** (`https://<host>:8080/v2/...`). Это не Kaspi Pay mobile API: в проекте нет мобильной авторизации, SMS, `entrance-pay.kaspi.kz`, `mtoken.kaspi.kz`, QR через неофициальные API или эмуляции приложения.

## Важные условия

- Компьютер администратора и Smart POS должны находиться в одной закрытой локальной сети.
- У Smart POS должен быть статический IP-адрес.
- Агент работает, только пока компьютер включён и активна пользовательская сессия Windows.
- Для IP-адреса терминала часто нужен `SMART_POS_TLS_MODE=ip_insecure`, поскольку сертификат терминала не совпадает с IP. Это явное, записываемое в лог ослабление проверки TLS; HTTP всё равно запрещён.
- Один терминал обрабатывает одну активную операцию. Вторая команда немедленно отклоняется с `terminal_busy`, в очередь не ставится.

## Установка и настройка

1. Установите [Python 3.12+](https://www.python.org/downloads/windows/) и убедитесь, что `python` доступен в PowerShell.
2. Скопируйте `.env.example` в `.env` и заполните значения. Не коммитьте `.env`.
3. Установите проект:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Ключевые параметры `.env`:

```dotenv
AGENT_ID=постоянный-uuid-агента
CRM_WS_URL=wss://crm.example.kz/api/v1/smart-pos/agent/ws
CRM_AGENT_TOKEN=выданный-CRM-токен
SMART_POS_HOST=192.168.1.100
SMART_POS_TLS_MODE=ip_insecure
SMART_POS_CLIENT_NAME=KoshakanSmartPosAgent
```

В production секреты Smart POS и CRM переносятся в Windows Credential Manager через `keyring`. `CRM_AGENT_TOKEN` в `.env` нужен для начальной настройки и больше не выводится. `DEVELOPMENT_MODE=true` включает явно отмеченное файловое хранилище `.data/secrets.json` только для локальной разработки.

## Первичный запуск

```powershell
python -m smart_pos_agent doctor
python -m smart_pos_agent register
python -m smart_pos_agent device-info
python -m smart_pos_agent run
```

`register` вызывает `GET /v2/register?name=...`; разрешите запрос на экране терминала. Полученные access/refresh-токены не показываются в терминале и не попадают в SQLite.

## Контрольная оплата и возврат

> Тестовую оплату запускайте только на реальном терминале с минимальной суммой и под контролем ответственного сотрудника.

```powershell
python -m smart_pos_agent test-payment --amount 10
python -m smart_pos_agent test-payment --amount 10 --yes
python -m smart_pos_agent test-refund --amount 10 --method qr --transaction-id 504711333
```

Сумма принимается только как положительное целое число KZT. Возврат должен использовать тот же метод, которым проведена оплата: для QR берётся `orderNumber`, для карты — `rrn`.

## Локальный mock CRM

Mock не требует реального Smart POS и удобен для проверки WebSocket-контракта.

Терминал 1:

```powershell
python tools/mock_crm_server.py
```

Терминал 2 (укажите для локальной проверки `CRM_WS_URL=ws://127.0.0.1:8765`):

```powershell
python -m smart_pos_agent run
```

В первом терминале доступны `device`, `payment 10`, `refund 10 qr 504711333`, `quit`. Без Smart POS операции устройства ожидаемо завершатся диагностическим событием; HTTP-интеграция покрыта автоматическими mock-тестами.

## Сборка и автозапуск Windows

```powershell
.\scripts\build-windows.ps1
.\scripts\install-autostart.ps1 -ExecutablePath "$PWD\dist\KoshakanSmartPosAgent\KoshakanSmartPosAgent.exe"
.\scripts\uninstall-autostart.ps1
```

Скрипт сборки создаёт venv, устанавливает зависимости, запускает проверки и формирует PyInstaller `onedir`-сборку в `dist/`. Планировщик создаёт задачу `Koshakan Smart POS Agent` при входе текущего пользователя и не передаёт секреты через аргументы.

## Диагностика и данные

- Логи: `%PROGRAMDATA%\KoshakanSmartPosAgent\logs\agent.log` (либо `.data/logs` при development mode).
- Состояние и история: `%PROGRAMDATA%\KoshakanSmartPosAgent\agent.sqlite3`.
- Состояние: `python -m smart_pos_agent show-status`.
- Удалить токены Smart POS: `python -m smart_pos_agent clear-smart-pos-credentials`.
- `401`/`403`: агент один раз обновляет токен через официальный `/v2/revoke` и повторяет запрос. При повторной ошибке зарегистрируйте терминал заново.
- `107`: на самом терминале не завершена предыдущая операция; CRM получает `terminal_busy`.
- `unknown`: агент запрашивает `/v2/actualize` не чаще заданного интервала. После таймаута статус — `manual_review`; не следует считать оплату неуспешной без сверки терминала.

## Ограничения

Официальный контракт не описывает endpoint удалённой отмены. Агент не изобретает такой API и не может удалённо отменить активную операцию; остановка приложения прекращает лишь локальный polling. Подробный контракт WebSocket — в [docs/crm-websocket-protocol.md](docs/crm-websocket-protocol.md), схема — в [docs/architecture.md](docs/architecture.md).
