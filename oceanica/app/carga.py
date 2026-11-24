"""Pantalla de carga: aparece en cuanto abre el programa, antes de cargar las pantallas y conectar con la base.

Muestra el colibrí (un GIF) volando sobre un fondo oscuro, con el nombre y una barra de progreso que sigue el avance
real de la carga, y dos sonidos: un aleteo al aparecer y un acorde al quedar listo.

Este módulo solo usa Qt (no importa el resto del sistema) para salir lo antes posible.
Las esperas largas (conectar, poner la base al día) corren en un hilo aparte para que la animación no se congele.
"""
from __future__ import annotations

import logging
import math
import struct
import sys
import threading
import time
import wave
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QMovie, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication, QWidget

from ..config import RAIZ

RECURSOS = Path(__file__).parent / "recursos"
GIF = RECURSOS / "colibri.gif"
log = logging.getLogger("oceanica")
MINIMO_VISIBLE = 2.2   # segundos: para alcanzar a ver el colibrí sin hacer esperar de más

# Sonidos generados aquí mismo (sin archivos de terceros); se escriben una vez y se tocan con winsound en Windows.
_FREC = 44100


def _wav(ruta: Path, muestras: bytearray) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_FREC)
        w.writeframes(bytes(muestras))


def _gen_aleteo() -> bytearray:
    import random
    random.seed(1)
    m = bytearray()
    dur, prev = 0.7, 0.0
    for i in range(int(_FREC * dur)):
        t = i / _FREC
        env = min(1, t / 0.08) * min(1, (dur - t) / 0.2)
        trem = 0.6 + 0.4 * math.sin(2 * math.pi * 45 * t)
        prev = prev * 0.82 + random.uniform(-1, 1) * 0.18     # ruido suave (pasa-bajos)
        v = 0.33 * env * trem * prev
        m += struct.pack("<h", int(max(-1, min(1, v)) * 32767))
    return m


def _gen_listo() -> bytearray:
    m = bytearray()
    for frec, dur in [(784, 0.07), (1047, 0.07), (1319, 0.07), (1568, 0.24)]:
        for i in range(int(_FREC * dur)):
            t = i / _FREC
            env = min(1, t / 0.004) * math.exp(-3.8 * t / dur)
            v = 0.5 * env * (math.sin(2 * math.pi * frec * t) + 0.2 * math.sin(4 * math.pi * frec * t))
            m += struct.pack("<h", int(max(-1, min(1, v)) * 32767))
    return m


_SONIDOS = {"aleteo": _gen_aleteo, "listo": _gen_listo}


def _reproducir(nombre: str) -> None:
    if sys.platform != "win32":
        return
    try:
        ruta = RAIZ / "sonidos" / f"{nombre}_carga.wav"
        if not ruta.exists():
            _wav(ruta, _SONIDOS[nombre]())
        import winsound
        winsound.PlaySound(str(ruta), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        log.debug("No se pudo reproducir el sonido de carga %s", nombre, exc_info=True)


class PantallaCarga(QWidget):
    ANCHO, ALTO = 640, 470

    def __init__(self):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(self.ANCHO, self.ALTO)
        self.texto = "Abriendo…"
        self.progreso = 0.0          # lo que se ve (0 a 1)
        self.objetivo = 0.1          # lo que ya se cargó de verdad
        self._inicio = time.monotonic()
        self._ultimo = self._inicio
        self._movie = None
        if GIF.exists():
            mv = QMovie(str(GIF))
            if mv.isValid():
                mv.setCacheMode(QMovie.CacheAll)
                mv.frameChanged.connect(self.update)
                mv.start()
                self._movie = mv
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._avanzar)
        self._timer.start(16)
        pantalla = QApplication.primaryScreen()
        if pantalla:
            self.move(pantalla.availableGeometry().center() - self.rect().center())
        QTimer.singleShot(120, lambda: _reproducir("aleteo"))

    # ------------------------------------------------------------------ avance
    def _avanzar(self):
        ahora = time.monotonic()
        dt = min(0.05, ahora - self._ultimo)
        self._ultimo = ahora
        meta = max(self.objetivo, min(0.97, self.progreso + 0.004 * dt))
        self.progreso += (meta - self.progreso) * min(1.0, dt * 3.0)
        self.update()

    def avance(self, fraccion: float):
        self.objetivo = max(self.objetivo, min(1.0, fraccion))

    def mensaje(self, texto: str, avance: float | None = None):
        self.texto = texto
        if avance is not None:
            self.avance(avance)
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
            hilo.join(0.015)
        if "error" in resultado:
            raise resultado["error"]
        return resultado.get("valor")

    def cerrar(self, ventana=None):
        """Espera lo mínimo para que se vea el colibrí, suena el acorde y se desvanece."""
        self.avance(1.0)
        self.texto = "Listo"
        limite = time.monotonic() + 1.5
        while time.monotonic() < limite and (time.monotonic() - self._inicio < MINIMO_VISIBLE or self.progreso < 0.995):
            QApplication.processEvents()
            time.sleep(0.01)
        self.progreso = 1.0
        _reproducir("listo")
        if ventana is not None:
            ventana.raise_()
        if self._movie is not None:
            self._movie.stop()
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(280)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InCubic)
        anim.finished.connect(self.close)
        anim.finished.connect(self._timer.stop)
        anim.start()
        self._anim = anim

    # ------------------------------------------------------------------ dibujo
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        caja = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        tarjeta = QPainterPath()
        tarjeta.addRoundedRect(caja, 26, 26)
        fondo = QLinearGradient(caja.topLeft(), caja.bottomLeft())
        fondo.setColorAt(0.0, QColor("#32526B"))
        fondo.setColorAt(0.55, QColor("#213E54"))
        fondo.setColorAt(1.0, QColor("#152A3C"))
        p.fillPath(tarjeta, fondo)

        p.save()
        p.setClipPath(tarjeta)
        gw, gh = 600.0, 338.0
        gx = (self.width() - gw) / 2
        gy = 20.0
        if self._movie is not None:
            cuadro = self._movie.currentPixmap()
            if not cuadro.isNull():
                p.drawPixmap(QRectF(gx, gy, gw, gh), cuadro, QRectF(cuadro.rect()))
        # difuminar los bordes del gif hacia el fondo (quita la franja oscura del video)
        azul = QColor("#213E54")
        ft = QLinearGradient(0, gy - 4, 0, gy + 56)
        ft.setColorAt(0.0, QColor(50, 82, 107)); ft.setColorAt(1.0, QColor(50, 82, 107, 0))
        p.fillRect(QRectF(gx, gy - 4, gw, 60), ft)
        fb = QLinearGradient(0, gy + gh - 70, 0, gy + gh + 8)
        c0 = QColor(azul); c0.setAlpha(0)
        fb.setColorAt(0.0, c0); fb.setColorAt(1.0, azul)
        p.fillRect(QRectF(gx, gy + gh - 70, gw, 80), fb)
        p.restore()

        p.setPen(QColor("#FFFFFF"))
        p.setFont(QFont("Segoe UI", 18, QFont.DemiBold))
        p.drawText(QRectF(caja.left(), 378, caja.width(), 34), Qt.AlignHCenter, "Lavandería Oceánica")
        p.setPen(QColor("#AFC6DA"))
        p.setFont(QFont("Segoe UI", 10))
        p.drawText(QRectF(caja.left(), 416, caja.width(), 22), Qt.AlignHCenter,
                   f"{self.texto}   {int(round(self.progreso * 100))} %")

        bw = self.width() - 200
        bx = 100.0
        by = 446.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawRoundedRect(QRectF(bx, by, bw, 5), 2.5, 2.5)
        grad = QLinearGradient(bx, 0, bx + bw, 0)
        grad.setColorAt(0.0, QColor("#27B5C6"))
        grad.setColorAt(1.0, QColor("#5AA9FF"))
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(bx, by, bw * self.progreso, 5), 2.5, 2.5)
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
