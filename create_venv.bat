@echo off
title Configurando slackbot-engenharia...

echo [1/5] Criando ambiente virtual...
uv venv
if errorlevel 1 ( echo ERRO ao criar o venv. & pause & exit /b )

echo [2/5] Ativando ambiente virtual...
call .venv\Scripts\activate
if errorlevel 1 ( echo ERRO ao ativar o venv. & pause & exit /b )

echo [3/5] Instalando dependencias base...
uv pip install -r requirements.txt
if errorlevel 1 ( echo ERRO ao instalar dependencias. & pause & exit /b )

echo [4/5] Instalando dependencias do bot...
uv pip install -r requirements-bot.txt
if errorlevel 1 ( echo ERRO ao instalar dependencias do bot. & pause & exit /b )

echo [5/5] Instalando projeto (modo editavel)...
uv pip install -e .
if errorlevel 1 ( echo ERRO ao instalar projeto. & pause & exit /b )

echo.
echo Tudo pronto! Para iniciar o bot: uv run -m bot.app
pause
