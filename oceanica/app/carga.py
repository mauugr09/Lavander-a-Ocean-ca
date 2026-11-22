"""Pantalla de carga: aparece en cuanto abre el programa, antes de cargar las pantallas y conectar con la base.

Este módulo solo usa Qt (no importa el resto del sistema) para salir lo antes posible.
Las esperas largas (conectar, poner la base al día) corren en un hilo aparte para que la animación no se congele.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

RECURSOS = Path(__file__).parent / "recursos"
_AZUL, _FONDO, _TEXTO, _SUAVE = "#0E7FB8", "#FFFFFF", "#14324A", "#6B7F93"
MINIMO_VISIBLE = 0.6   # segundos: si todo carga muy rápido, que no sea solo un parpadeo


class PantallaCarga(QWidget):
    def __init__(self):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(460, 296)
        self.texto = "Abriendo…"
        self._fase = 0.0
        self._inicio = time.monotonic()
        logo = RECURSOS / "logo.png"
        self._logo = QPixmap(str(logo)) if logo.exists() else QPixmap()
        if not self._logo.isNull():
            self._logo = self._logo.scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._avanzar)
        self._timer.start(16)
        pantalla = QApplication.primaryScreen()
        if pantalla:
            self.move(pantalla.availableGeometry().center() - self.rect().center())

    def _avanzar(self):
        self._fase = (self._fase + 0.012) % 1.0
        self.update()

    def mensaje(self, texto: str):
        self.texto = texto
        self.update()
        QApplication.processEvents()

    def esperar(self, texto: str, fn, *args, **kwargs):
        """Corre `fn` en un hilo mientras la pantalla sigue animada; devuelve su resultado o vuelve a lanzar su error."""
        self.mensaje(texto)
        resultado: dict = {}

        def trabajo():
            try:
                resultado["valor"] = fn(*args, **kwargs)
            except BaseException as e:   # se vuelve a lanzar en el hilo principal
                resultado["error"] = e
        hilo = threading.Thread(target=trabajo, daemon=True)
        hilo.start()
        while hilo.is_alive():
            QApplication.processEvents()
            hilo.join(0.02)
        if "error" in resultado:
            raise resultado["error"]
        return resultado.get("valor")

    def cerrar(self, ventana=None):
        """Espera lo mínimo para no parpadear y se desvanece."""
        while time.monotonic() - self._inicio < MINIMO_VISIBLE:
            QApplication.processEvents()
            time.sleep(0.01)
        if ventana is not None:
            ventana.raise_()
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(220)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InCubic)
        anim.finished.connect(self.close)
        anim.finished.connect(self._timer.stop)
        anim.start()
        self._anim = anim

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        caja = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        sombra = QPainterPath()
        sombra.addRoundedRect(caja.translated(0, 3), 22, 22)
        p.fillPath(sombra, QColor(20, 50, 74, 40))
        fondo = QPainterPath()
        fondo.addRoundedRect(caja, 22, 22)
        p.fillPath(fondo, QColor(_FONDO))
        y = caja.top() + 30
        if not self._logo.isNull():
            p.drawPixmap(int(caja.center().x() - self._logo.width() / 2), int(y), self._logo)
            y += self._logo.height() + 14
        p.setPen(QColor(_TEXTO))
        p.setFont(QFont("Segoe UI", 15, QFont.DemiBold))
        p.drawText(QRectF(caja.left(), y, caja.width(), 30), Qt.AlignHCenter, "Lavandería Oceánica")
        y += 36
        p.setPen(QColor(_SUAVE))
        p.setFont(QFont("Segoe UI", 10))
        p.drawText(QRectF(caja.left(), y, caja.width(), 22), Qt.AlignHCenter, self.texto)
        # barra que corre de izquierda a derecha
        y += 34
        ancho = caja.width() - 120
        barra = QRectF(caja.left() + 60, y, ancho, 6)
        riel = QPainterPath()
        riel.addRoundedRect(barra, 3, 3)
        p.fillPath(riel, QColor("#E3EEF6"))
        largo = ancho * 0.32
        x = barra.left() - largo + (ancho + largo) * self._fase
        tramo = QRectF(max(barra.left(), x), y, min(x + largo, barra.right()) - max(barra.left(), x), 6)
        if tramo.width() > 0:
            pieza = QPainterPath()
            pieza.addRoundedRect(tramo, 3, 3)
            p.fillPath(pieza, QColor(_AZUL))
        p.end()


def iniciar_pantalla_carga() -> PantallaCarga | None:
    """Crea la aplicación de Qt y muestra la pantalla de carga. Sin pantalla (pruebas, servidores) devuelve None."""
    app = QApplication.instance() or QApplication(sys.argv)
    if app.platformName() in ("offscreen", "minimal"):
        return None
    pantalla = PantallaCarga()
    pantalla.show()
    app.processEvents()
    return pantalla
