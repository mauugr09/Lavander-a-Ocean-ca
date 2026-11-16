"""Arranque de la aplicación de escritorio."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import mysql.connector
from PySide6.QtCore import QLibraryInfo, QLocale, Qt, QTranslator
from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

from ..config import CARPETA_LOGS, RUTA_CONFIG, cargar_config
from ..db import conectar
from . import tema
from .contexto import Contexto
from .ventana import Ventana

RECURSOS = Path(__file__).parent / "recursos"


def _configurar_log() -> None:
    CARPETA_LOGS.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(CARPETA_LOGS / "oceanica.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger("oceanica").addHandler(h)
    logging.getLogger("oceanica").setLevel(logging.INFO)


def _forzar_tema_claro(app: QApplication) -> None:
    """El sistema usa colores claros aunque Windows esté en modo oscuro (si no, algunos paneles salen negros)."""
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)  # Qt 6.8+
    except AttributeError:
        pass
    p = QPalette()
    claro = {
        QPalette.Window: tema.FONDO, QPalette.WindowText: tema.TEXTO, QPalette.Base: "#FFFFFF",
        QPalette.AlternateBase: "#F6FAFD", QPalette.Text: tema.TEXTO, QPalette.Button: "#FFFFFF",
        QPalette.ButtonText: tema.TEXTO, QPalette.ToolTipBase: "#FFFFFF", QPalette.ToolTipText: tema.TEXTO,
        QPalette.Highlight: "#CFEAF7", QPalette.HighlightedText: tema.TEXTO, QPalette.PlaceholderText: "#8A9AAD",
        QPalette.Link: tema.PRIMARIO, QPalette.BrightText: "#FFFFFF", QPalette.Light: "#FFFFFF",
        QPalette.Midlight: "#EEF3F7", QPalette.Mid: tema.BORDE, QPalette.Dark: "#9FB0C0", QPalette.Shadow: "#5B6F86",
    }
    for rol, color in claro.items():
        p.setColor(rol, QColor(color))
    for rol in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, rol, QColor("#9FB0C0"))
    app.setPalette(p)


def preparar_aplicacion() -> QApplication:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Oceánica Gestión")
    app.setStyle("Fusion")
    _forzar_tema_claro(app)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(tema.HOJA_ESTILO)
    app.setWindowIcon(QIcon(str(RECURSOS / "icono.png")))
    # Botones y textos estándar de Qt en español («Sí», «No», «Cancelar», calendario…)
    traductor = QTranslator(app)
    if traductor.load(QLocale("es_MX"), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(traductor)
    QLocale.setDefault(QLocale("es_MX"))
    return app


def main() -> int:
    _configurar_log()
    app = preparar_aplicacion()
    cfg = cargar_config()
    try:
        if not RUTA_CONFIG.exists() and not cfg.password:
            raise FileNotFoundError("No existe config.ini")
        conn = conectar(cfg)
    except (mysql.connector.Error, FileNotFoundError) as e:
        QMessageBox.critical(None, "Oceánica Gestión",
                             "No se pudo conectar con la base de datos.\n\n"
                             "• Revise que el servicio de MariaDB/MySQL esté encendido.\n"
                             "• Si es la primera vez: python -m oceanica.init_db (con root)\n  o, si la base ya existe: python -m oceanica.configurar\n\n"
                             f"Detalle: {e}")
        return 1
    ctx = Contexto(conn, cfg)
    ventana = Ventana(ctx)
    ventana.showMaximized()
    return app.exec()
