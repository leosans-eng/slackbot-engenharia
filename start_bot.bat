@echo off
cd /d "%~dp0"
title slackbot-engenharia

echo Encerrando instancia anterior do bot, se houver...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.Name -notmatch '^(powershell|pwsh|cmd)\.exe$' -and $_.CommandLine -match '-m\s+bot\.app' } | ForEach-Object { Write-Host ('  encerrando PID ' + $_.ProcessId + ' (' + $_.Name + ')'); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Start-Sleep -Seconds 1"

:loop
echo.
echo Iniciando bot... Ctrl+R reinicia. Ctrl+C encerra.
uv run -m bot.app
if %ERRORLEVEL%==42 goto loop

echo.
echo Bot encerrado.
pause
