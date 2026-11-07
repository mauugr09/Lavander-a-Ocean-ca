"""Arranque de la aplicación de escritorio."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import mysql.connector
from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtGui import QFont, QIcon
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


def _traducir_qt(app: QApplication) -> None:
    """Botones estándar de Qt en español («Aceptar», «Cancelar») en lugar de «OK», «Cancel»."""
    if getattr(app, "_traductor_es", None):
        return
    QLocale.setDefault(QLocale(QLocale.Spanish, QLocale.Mexico))
    t = QTranslator(app)
    if t.load(QLocale(QLocale.Spanish), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(t)
        app._traductor_es = t
    else:  # sin el archivo de traducción la aplicación funciona igual, solo con botones en inglés
        logging.getLogger("oceanica").warning("No se encontró la traducción de Qt al español (qtbase_es.qm)")


def preparar_aplicacion() -> QApplication:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Oceánica Gestión")
    _traducir_qt(app)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(tema.HOJA_ESTILO)
    app.setWindowIcon(QIcon(str(RECURSOS / "icono.png")))
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
                             "• Revisa que el servicio de MariaDB/MySQL esté encendido.\n"
                             "• Si es la primera vez: python -m oceanica.init_db (con root)\n  o, si la base ya existe: python -m oceanica.configurar\n\n"
                             f"Detalle: {e}")
        return 1
    ctx = Contexto(conn, cfg)
    ventana = Ventana(ctx)
    ventana.showMaximized()
    return app.exec()
