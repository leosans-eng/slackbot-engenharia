@echo off
title Configurando ambiente...

echo [1/3] Criando ambiente virtual...
uv venv
if errorlevel 1 ( echo ERRO ao criar o venv. & pause & exit /b )

echo [2/3] Ativando ambiente virtual...
call .venv\Scripts\activate
if errorlevel 1 ( echo ERRO ao ativar o venv. & pause & exit /b )

echo [3/3] Instalando dependencias...
uv pip install -r requirements.txt
if errorlevel 1 ( echo ERRO ao instalar dependencias. & pause & exit /b )

echo.
echo Tudo pronto! Ambiente configurado com sucesso.
pause