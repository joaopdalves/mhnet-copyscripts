@echo off
REM ============================================================
REM  build_exe.bat
REM  Gera o arquivo "Mhnet CopyScripts.exe" (Windows) a partir do app.py
REM  Execute este arquivo DENTRO da pasta do projeto, no Windows.
REM ============================================================

echo.
echo === Mhnet CopyScripts - gerador do .exe ===
echo.

REM 1) Verifica se o Python esta instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao foi encontrado no seu computador.
    echo Baixe e instale em: https://www.python.org/downloads/
    echo IMPORTANTE: marque a opcao "Add Python to PATH" durante a instalacao.
    pause
    exit /b 1
)

REM 2) Instala o PyInstaller (caso ainda nao esteja instalado)
echo Instalando/atualizando o PyInstaller e a reportlab...
python -m pip install --upgrade pyinstaller "reportlab==4.2.0"

REM 3) Gera o executavel
echo.
echo Gerando o executavel, isso pode levar 1 a 2 minutos...
python -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "Mhnet CopyScripts" ^
    --collect-submodules reportlab.pdfbase ^
    --exclude-module numpy ^
    --icon "imagens\mhnet_icon.ico" ^
    --add-data "imagens;imagens" ^
    app.py

echo.
if exist "dist\Mhnet CopyScripts.exe" (
    echo ============================================================
    echo  SUCESSO! Seu executavel esta em:  dist\Mhnet CopyScripts.exe
    echo  Voce pode mover esse arquivo para qualquer lugar do PC,
    echo  criar um atalho na area de trabalho, etc.
    echo ============================================================
) else (
    echo [ERRO] Algo deu errado ao gerar o .exe. Veja as mensagens acima.
)

pause
