# Выпуск Windows-версии

1. Убедитесь, что `main` чистая и синхронизирована: `git pull --ff-only`.
2. Обновите единственную точку версии — `src/smart_pos_agent/version.py`.
3. Запустите `./scripts/build-windows.ps1` и проверьте оба каталога в `dist/`.
4. Выберите отсутствующий semver-тег и создайте annotated tag:

   ```powershell
   git tag -a v0.2.0 -m "Koshakan Smart POS Agent v0.2.0"
   git push origin v0.2.0
   ```

5. Workflow `Release Windows application` сверяет версию package и тег, выполняет quality suite и сборку, запускает smoke/help/version, проверяет отсутствие secret files/credential patterns, создаёт ZIP и SHA-256, после чего публикует GitHub Release.
6. Откройте Release и убедитесь в наличии:
   - `KoshakanSmartPosAgent-vX.Y.Z-win64.zip`;
   - `KoshakanSmartPosAgentCli-vX.Y.Z-win64.zip`;
   - `SHA256SUMS.txt`.
7. Скачайте GUI ZIP, распакуйте его во временную папку и запустите `KoshakanSmartPosAgent.exe --smoke-test`.

Не перемещайте и не перезаписывайте опубликованный тег, не используйте force push и не удаляйте Release. Если workflow не прошёл после публикации коммита, исправьте код в `main` и выпустите новую patch-версию.
