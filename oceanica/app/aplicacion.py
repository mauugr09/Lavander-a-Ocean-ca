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
from .efectos import efectos
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


def _esperar(pantalla, texto, fn, *args):
    """Con pantalla de carga, la espera corre en un hilo y la animación sigue; sin ella (pruebas), directo."""
    return pantalla.esperar(texto, fn, *args) if pantalla is not None else fn(*args)


def actualizar_al_abrir(cfg, pantalla=None) -> bool:
    """Si la versión nueva del programa trae cambios para la base, los aplica solos (con respaldo previo), para que
    nadie tenga que correr «migrar». Devuelve False si no se pudo: el programa no debe abrir con la base a medias."""
    from .. import migrar
    log = logging.getLogger("oceanica")
    try:
        r = _esperar(pantalla, "Revisando que la base de datos esté al día…", migrar.actualizar, cfg)
    except migrar.ErrorActualizacion as e:
        log.error("No se pudo actualizar la base al abrir: %s", e)
        if pantalla is not None:
            pantalla.hide()
        QMessageBox.critical(None, "Oceánica Gestión",
                             "El programa se actualizó, pero no pudo poner al día la base de datos, así que no se abrirá "
                             "para no arriesgar la información.\n\n"
                             "Avise a la encargada: el detalle y la forma de regresar a como estaba quedaron en la "
                             "carpeta logs.\nMientras tanto, anote las órdenes en papel.")
        return False
    if r["aplicadas"]:
        log.info("Base actualizada al abrir: migraciones %s; respaldo previo: %s", r["aplicadas"], r["respaldo"])
    return True


def main(pantalla=None) -> int:
    """`pantalla`: la pantalla de carga que ya se mostró en `__main__` (None en las pruebas)."""
    _configurar_log()
    app = preparar_aplicacion()
    efectos.instalar(app)
    cfg = cargar_config()
    if not RUTA_CONFIG.exists() and not cfg.password:
        # Primera vez en esta computadora: el asistente crea la base y la cuenta de la encargada, sin consola.
        from .asistente import AsistenteInstalacion
        if pantalla is not None:
            pantalla.hide()
        asistente = AsistenteInstalacion()
        if not asistente.exec() or not asistente.resultado:
            return 1
        cfg = asistente.resultado["cfg"]
        if pantalla is not None:
            pantalla.show()
    try:
        conn = _esperar(pantalla, "Conectando con la base de datos…", conectar, cfg)
    except mysql.connector.Error:
        # Sistema ya instalado que hoy no conecta: lo ve el empleado al abrir. El detalle técnico va al registro.
        logging.getLogger("oceanica").exception("No se pudo conectar con la base de datos al iniciar")
        if pantalla is not None:
            pantalla.hide()
        QMessageBox.critical(None, "Oceánica Gestión",
                             "No se pudo abrir el sistema porque la base de datos no responde.\n\n"
                             "1. Cierre este aviso y reinicie la computadora.\n"
                             "2. Vuelva a abrir Oceánica.\n\n"
                             "Si sigue igual, avise a la encargada: el detalle quedó en la carpeta logs.\n"
                             "Mientras tanto, anote las órdenes en papel.")
        return 1
    if not actualizar_al_abrir(cfg, pantalla):
        conn.close()
        return 1
    if pantalla is not None:
        pantalla.mensaje("Preparando las pantallas…")
    efectos.configurar_desde(conn)
    ctx = Contexto(conn, cfg)
    ventana = Ventana(ctx)
    ventana.showMaximized()
    if pantalla is not None:
        pantalla.cerrar(ventana)
    return app.exec()
