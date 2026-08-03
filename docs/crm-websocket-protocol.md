# CRM WebSocket protocol v1

## Соединение и авторизация

Агент открывает исходящее соединение `wss://<crm-host>/api/v1/smart-pos/agent/ws` с заголовком `Authorization: Bearer <CRM_AGENT_TOKEN>`. Для локального mock допускается `ws://`. Все события агента имеют:

```json
{"type":"...","protocolVersion":1,"messageId":"uuid","timestamp":"2026-01-01T00:00:00+00:00","payload":{}}
```

Время всегда UTC ISO 8601. CRM команду передаёт как JSON и должна считать `commandId` ключом идемпотентности.

## Команды

```json
{"type":"device.check","commandId":"uuid","operationId":null,"payload":{}}
{"type":"payment.start","commandId":"uuid","operationId":"uuid","payload":{"amount":25000,"ownCheque":false}}
{"type":"refund.start","commandId":"uuid","operationId":"uuid","payload":{"amount":10000,"method":"qr","transactionId":"504711333","ownCheque":false}}
```

`amount` — строго положительное целое KZT (не float). Для возврата `method` только `qr`, `card`, `alaqan`; QR `transactionId` — `orderNumber`, card — `rrn`. Неизвестная или невалидная команда не разрывает сокет: агент возвращает `protocol.error` с `unknown_command` или `invalid_command`.

## События

Типы: `agent.hello`, `agent.heartbeat`, `command.accepted`, `command.rejected`, `device.status`, `payment.started`, `payment.status`, `payment.completed`, `payment.failed`, `payment.manual_review`, и симметричные `refund.*`, `agent.error`, `protocol.error`.

После подключения отправляется `agent.hello` с `agentId`, `agentName`, `agentVersion`, `platform: windows` и `terminal` (`reachable`, `terminalId`, `serialNumber`, `posNum`). Каждые 15 секунд по умолчанию отправляется `agent.heartbeat`:

```json
{"type":"agent.heartbeat","protocolVersion":1,"messageId":"uuid","timestamp":"...","payload":{"agentId":"...","terminalStatus":"ready","activeOperationId":null}}
```

Для промежуточного статуса:

```json
{"type":"payment.status","protocolVersion":1,"messageId":"uuid","timestamp":"...","payload":{"commandId":"...","operationId":"...","processId":"...","status":"wait","subStatus":"WaitUser"}}
```

Итоговая success-операция передаёт `amount`, `method`, `transactionId`, `orderNumber`, `rrn`, `terminalId`, `chequeInfo`, `rawResponse`. Если терминал передал `chequeInfo.amount`, агент добавляет нормализованный целочисленный `reportedAmount`; CRM не должна считать запрошенную сумму подтверждённой только по команде.

## Статусы и ошибки

Основные POS-статусы: `wait`, `success`, `fail`, `unknown`. `subStatus`: `Initialize`, `WaitUser`, `WaitForQrConfirmation`, `ProcessingCard`, `WaitForPinCode`, `ProcessRefund`, `QrTransactionSuccess`, `QrTransactionFailure`, `CardTransactionSuccess`, `CardTransactionFailure`, `ProcessCancelled`.

HTTP `401`/`403` приводят к одному refresh/retry; `107` — `command.rejected` с `reason: terminal_busy`; ошибки POS `100`, `101`, `105`, `106`, `108`, `999` нормализуются в terminal/API error. `unknown` не означает неуспех: агент вызывает `/actualize` не чаще 10 секунд и после `UNKNOWN_ACTUALIZE_TIMEOUT_SECONDS` публикует `*.manual_review`.

## Идемпотентность, reconnect и отмена

Команда сохраняется в SQLite **до** запуска POS. Тот же `commandId` не выполняется повторно: агент возвращает сохранённое или актуальное состояние. При рестарте незавершённый `processId` продолжает опрашиваться. На один терминал допускается одна активная операция; вторая не ставится в очередь и получает `terminal_busy` с `activeOperationId`.

При потере сокета агент использует exponential backoff с jitter (1–60 секунд по умолчанию), затем повторяет hello и передаёт актуальное состояние. В официальном Smart POS API нет задокументированного удалённого cancel endpoint. Поэтому CRM не должна ожидать удалённой отмены: завершение приложения прекращает только polling, а не операцию на терминале.
