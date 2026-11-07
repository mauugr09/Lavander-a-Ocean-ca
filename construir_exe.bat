@echo off
rem Genera el programa para Windows (carpeta dist\Oceanica) y, si esta Inno Setup, el instalador.
rem Requiere Python 3.12 o superior instalado con "Add to PATH". Hay que ejecutarlo en Windows.
cd /d "%~dp0"
echo == Preparando entorno de construccion ==
python -m venv .venv_exe || goto :error
call .venv_exe\Scripts\activate.bat
python -m pip install --upgrade pip || goto :error
pip install -r requirements.txt pyinstaller || goto :error
echo == Construyendo ==
pyinstaller oceanica.spec --noconfirm --clean || goto :error
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
  echo == Creando instalador ==
  "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" instalador.iss || goto :error
  echo Listo: instalador en dist\Instalar_Oceanica.exe
) else (
  echo Listo: programa en dist\Oceanica\Oceanica.exe
  echo Para crear el instalador, instala Inno Setup 6 ^(jrsoftware.org^) y vuelve a ejecutar este archivo.
)
pause
exit /b 0
:error
echo.
echo ERROR: no se pudo construir. Copia el mensaje de arriba y mandalo.
pause
exit /b 1
