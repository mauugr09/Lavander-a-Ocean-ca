@echo off
rem Abre Lavanderia Oceanica sin ventana de consola.
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 (
  echo No se encontro Python. Instala Python 3.12 o superior y marca "Add to PATH".
  pause
  exit /b 1
)
start "" pythonw -m oceanica
