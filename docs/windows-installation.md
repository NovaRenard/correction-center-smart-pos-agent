# Установка в Windows

Установите Python 3.12+, склонируйте репозиторий и заполните `.env` по README. Для production оставьте `DEVELOPMENT_MODE=false`, чтобы ключи хранились в Windows Credential Manager.

Соберите агент `./scripts/build-windows.ps1`, затем укажите абсолютный путь к exe:

```powershell
./scripts/install-autostart.ps1 -ExecutablePath "C:\Agents\KoshakanSmartPosAgent.exe"
```

Задача планировщика запускается при входе текущего пользователя. Проверьте её в Task Scheduler и логи в `%PROGRAMDATA%\KoshakanSmartPosAgent\logs`. Для удаления: `./scripts/uninstall-autostart.ps1`.
