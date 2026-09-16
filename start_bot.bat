@echo off
cd /d "%~dp0"
title slackbot-engenharia

echo Encerrando instancia anterior do bot, se houver...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.Name -notmatch '^(powershell|pwsh|cmd)\.exe$' -and $_.CommandLine -match '-m\s+bot\.app' } | ForEach-Object { Write-Host ('  encerrando PID ' + $_.ProcessId + ' (' + $_.Name + ')'); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Start-Sleep -Seconds 1"

echo Iniciando bot...
uv run -m bot.app
pause
