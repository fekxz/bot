@echo off
setlocal
cd /d "%~dp0"
title AloneBot

where py >nul 2>&1
if errorlevel 1 (
    echo.
    echo Python nao foi encontrado. Instale o Python 3.10 ou superior em https://www.python.org/downloads/
    echo Durante a instalacao, marque a opcao "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

if not exist ".env" (
    echo.
    echo Arquivo .env nao encontrado.
    echo Copie .env.example, renomeie para .env e coloque o token do bot.
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente virtual...
    py -3 -m venv .venv
    if errorlevel 1 goto :erro

    echo Instalando dependencias...
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 goto :erro
)

echo Iniciando AloneBot...
.venv\Scripts\python.exe bot.py
echo.
echo O bot foi encerrado.
pause
exit /b 0

:erro
echo.
echo Nao foi possivel preparar o bot. Confira sua instalacao do Python e a conexao com a internet.
pause
exit /b 1
