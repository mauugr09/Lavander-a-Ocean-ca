# -*- mode: python ; coding: utf-8 -*-
# Genera dist/Oceanica/ con dos programas que comparten las mismas librerías:
#   Oceanica.exe       el programa (sin ventana negra)
#   OceanicaAdmin.exe  la misma aplicación con consola, para instalar, migrar y respaldar
import sys
from PyInstaller.utils.hooks import collect_submodules

ocultos = collect_submodules("mysql.connector") + ["oceanica.migrar", "oceanica.configurar", "oceanica.init_db", "oceanica.respaldos", "bcrypt", "reportlab.graphics.barcode.code128"]
if sys.platform == "win32":
    ocultos += ["win32print", "win32timezone"]

a = Analysis(
    ["oceanica/__main__.py"],
    pathex=["."],
    datas=[("db/migrations", "db/migrations"), ("oceanica/app/recursos", "oceanica/app/recursos")],
    hiddenimports=ocultos,
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick",
              "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization"],
    noarchive=False,
)
pyz = PYZ(a.pure)
icono = "oceanica/app/recursos/oceanica.ico"
programa = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Oceanica", console=False, icon=icono)
consola = EXE(pyz, a.scripts, [], exclude_binaries=True, name="OceanicaAdmin", console=True, icon=icono)
COLLECT(programa, consola, a.binaries, a.datas, name="Oceanica")
