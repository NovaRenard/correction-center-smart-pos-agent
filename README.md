# Koshakan Smart POS Agent

Windows-агент, который соединяет Correction Center CRM с физическим Kaspi Smart POS только через официальный локальный HTTPS API терминала. CRM остаётся источником истины; агент выполняет операции и передаёт их результат по существующему WebSocket-протоколу.

## Tray-приложение

Основной способ работы — `KoshakanSmartPosAgent.exe`. После запуска значок остаётся возле часов Windows, а закрытие окна через `X` только скрывает его: агент продолжает работать в фоне. Полное завершение доступно только через меню значка → «Выход».

Цвет значка:

- зелёный — CRM подключена, Smart POS готов;
- синий — выполняется операция;
- жёлтый — идёт переподключение или требуется настройка;
- красный — CRM/терминал недоступен либо нужна ручная проверка;
- серый — агент остановлен.

GUI и CLI используют одно ядро. В GUI нет локального веб-сервера, браузерного интерфейса или Electron.

## Где скачать готовую версию

Откройте страницу [GitHub Releases](https://github.com/NovaRenard/correction-center-smart-pos-agent/releases) и скачайте `KoshakanSmartPosAgent-vX.Y.Z-win64.zip`.

1. Распакуйте весь архив в отдельную папку.
2. Не запускайте EXE прямо из ZIP.
3. Запустите `KoshakanSmartPosAgent.exe`.
4. Пройдите первый запуск, затем значок появится возле часов.

Windows SmartScreen может запросить подтверждение, потому что приложение пока не подписано code-signing сертификатом. Проверяйте источник архива и SHA-256 из `SHA256SUMS.txt`.

## Первый запуск и настройка

Мастер запрашивает название агента, CRM WebSocket URL, CRM Agent Token, IP/порт Smart POS, имя клиента и TLS mode. `AGENT_ID` генерируется один раз и хранится как несекретная настройка. CRM Agent Token, а также access/refresh-токены Smart POS, сохраняются через Windows Credential Manager (в development mode используется явно отмеченный `SecretStore`). Они не записываются в `config.json`, SQLite, аргументы запуска или окно приложения.

Несекретная конфигурация находится в `%PROGRAMDATA%\KoshakanSmartPosAgent\config.json`; при `DEVELOPMENT_MODE=true` — в `.data\config.json`. Запись атомарная. Приоритет: environment variables и `.env` (для разработки/автоматизации) → persistent config → defaults. Это сохраняет существующие CLI-сценарии с `.env`.

## Подключение Smart POS

В окне выберите «Подключить терминал»:

1. На Smart POS откройте «Панель администратора» → «Защита интеграции» → «Настроить доступ».
2. Нажмите «Отправить запрос регистрации» в приложении.
3. Подтвердите запрос на экране терминала.

Токены никогда не отображаются. Агент использует только `https://<host>:8080/v2/...`; мобильные Kaspi endpoint’ы, SMS-авторизация и выдуманный cancel endpoint не используются.

## Автозапуск Windows

В меню tray или настройках включите «Запускать вместе с Windows». Создаётся задача текущего пользователя `Koshakan Smart POS Agent`, запускающая GUI EXE без аргументов и секретов. В исходниках автозапуск намеренно не регистрируется: включайте его в собранном приложении.

## CLI

`KoshakanSmartPosAgentCli.exe` — отдельный console-инструмент диагностики. В исходниках доступны прежние команды:

```powershell
python -m smart_pos_agent doctor
python -m smart_pos_agent register
python -m smart_pos_agent device-info
python -m smart_pos_agent run
python -m smart_pos_agent show-status
python -m smart_pos_agent --version
```

Реальные операции остаются осознанными действиями: `test-payment` и `test-refund` требуют физический терминал и не должны использоваться без контроля ответственного сотрудника.

## Логи и данные

- логи: `%PROGRAMDATA%\KoshakanSmartPosAgent\logs\agent.log`;
- SQLite: `%PROGRAMDATA%\KoshakanSmartPosAgent\agent.sqlite3`;
- development mode: `.data\logs` и `.data\agent.sqlite3`.

Одна активная операция на терминал остаётся строгим правилом. `unknown` обрабатывается через официальный `actualize`; после таймаута используется `manual_review`, а повторную оплату запускать нельзя до сверки с терминалом.

## Сборка и GitHub Actions

```powershell
.\scripts\build-windows.ps1
```

Скрипт создаёт/использует `.venv`, устанавливает зависимости, выполняет ruff, mypy и pytest, собирает GUI и CLI в `dist/`, затем проверяет GUI `--smoke-test`, CLI `--help` и `--version`.

Обычный CI запускается на push и pull request: Ubuntu выполняет quality suite, Windows формирует скачиваемый artifact на 7 дней. Тег запускает release workflow, создающий два portable ZIP и `SHA256SUMS.txt` только после успешных проверок и safety scan.

## Как выпустить новую версию

Версия задаётся только в `src/smart_pos_agent/version.py`. Версия package должна совпадать с тегом без префикса `v`.

```powershell
git checkout main
git pull --ff-only
git tag -a v0.2.0 -m "Koshakan Smart POS Agent v0.2.0"
git push origin v0.2.0
```

После завершения workflow: GitHub → repository → Releases → `v0.2.0` → Assets → `KoshakanSmartPosAgent-v0.2.0-win64.zip`. Более подробный порядок — в [docs/releasing.md](docs/releasing.md), поведение окна — в [docs/desktop-app.md](docs/desktop-app.md).

## Ограничения

- Компьютер администратора и Smart POS должны находиться в закрытой локальной сети; терминалу нужен стабильный IP.
- Для IP терминала может потребоваться явный `SMART_POS_TLS_MODE=ip_insecure`; HTTP не поддерживается.
- У официального API нет удалённой отмены: выход из программы не отменяет операцию на терминале.
- Этот проект не заявляет о физической проверке оплаты без реального подключённого Smart POS.
