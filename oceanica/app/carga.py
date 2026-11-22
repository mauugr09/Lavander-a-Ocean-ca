"""Pantalla de carga: aparece en cuanto abre el programa, antes de cargar las pantallas y conectar con la base.

Animación: el logo dentro de una burbuja de jabón iridiscente que ondula; el logo se va «llenando» de abajo hacia
arriba conforme avanza la carga real, con burbujas que suben por el fondo. Todo se dibuja con QPainter (sin videos ni
archivos extra).

Este módulo solo usa Qt (no importa el resto del sistema) para salir lo antes posible.
Las esperas largas (conectar, poner la base al día) corren en un hilo aparte para que la animación no se congele.
"""
from __future__ import annotations

import math
import random
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QRadialGradient)
from PySide6.QtWidgets import QApplication, QWidget

RECURSOS = Path(__file__).parent / "recursos"
_TEXTO, _SUAVE = "#14324A", "#5E7488"
MINIMO_VISIBLE = 1.6   # segundos: lo justo para que se vea la animación sin hacer esperar de más
_IRIS = ["#7FDBFF", "#5B8CFF", "#A77BFF", "#FF8AD8", "#FFD27A", "#9BFFCF", "#7FDBFF"]   # película de jabón


class _Pompa:
    """Burbuja del fondo (como las del segundo video): transparente, borde brillante, sube con vaivén."""

    def __init__(self, ancho: float, alto: float, abajo: bool):
        self.radio = random.choice([random.uniform(8, 22)] * 3 + [random.uniform(28, 70)])
        self.x = random.uniform(0, ancho)
        self.y = alto + self.radio + random.uniform(0, alto * 0.4) if abajo else random.uniform(0, alto)
        self.vel = random.uniform(0.35, 1.0) * (1.3 if self.radio < 22 else 1.0)
        self.fase = random.uniform(0, math.tau)
        self.amp = random.uniform(6, 20)
        self.giro = random.uniform(0, 360)
        self.alfa = random.uniform(0.45, 0.95)


class PantallaCarga(QWidget):
    ANCHO, ALTO = 620, 470

    def __init__(self):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(self.ANCHO, self.ALTO)
        self.texto = "Abriendo…"
        self.t = 0.0                 # tiempo de la animación (s)
        self.progreso = 0.0          # lo que se ve (0 a 1)
        self.objetivo = 0.15         # lo que ya se cargó de verdad
        self._inicio = time.monotonic()
        self._ultimo = self._inicio
        logo = RECURSOS / "logo.png"
        self._logo = QPixmap(str(logo)) if logo.exists() else QPixmap()
        self._pompas = [_Pompa(self.ANCHO, self.ALTO, abajo=False) for _ in range(18)]
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._avanzar)
        self._timer.start(16)
        pantalla = QApplication.primaryScreen()
        if pantalla:
            self.move(pantalla.availableGeometry().center() - self.rect().center())

    # ------------------------------------------------------------------ avance
    def _avanzar(self):
        ahora = time.monotonic()
        dt = min(0.05, ahora - self._ultimo)
        self._ultimo = ahora
        self.t += dt
        # se acerca a lo cargado; si algo tarda, sigue avanzando muy despacio para que no parezca trabado
        meta = max(self.objetivo, min(0.97, self.progreso + 0.004 * dt))
        self.progreso += (meta - self.progreso) * min(1.0, dt * 3.2)
        for i, b in enumerate(self._pompas):
            b.y -= b.vel * dt * 60
            if b.y < -b.radio * 2:
                self._pompas[i] = _Pompa(self.ANCHO, self.ALTO, abajo=True)
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
        """Termina de llenar el logo, espera lo mínimo para que se vea y se desvanece."""
        self.avance(1.0)
        self.texto = "Listo"
        limite = time.monotonic() + 1.5   # nunca se queda más de esto esperando a que se llene
        while time.monotonic() < limite and (time.monotonic() - self._inicio < MINIMO_VISIBLE or self.progreso < 0.995):
            QApplication.processEvents()
            time.sleep(0.01)
        self.progreso = 1.0
        if ventana is not None:
            ventana.raise_()
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(260)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InCubic)
        anim.finished.connect(self.close)
        anim.finished.connect(self._timer.stop)
        anim.start()
        self._anim = anim

    # ------------------------------------------------------------------ dibujo
    def _contorno(self, c: QPointF, r: float) -> QPainterPath:
        """Borde de la burbuja que ondula despacio (como la del primer video)."""
        camino = QPainterPath()
        n = 72
        for i in range(n + 1):
            a = math.tau * i / n
            d = (math.sin(3 * a + self.t * 1.7) * 0.022 + math.sin(2 * a - self.t * 1.1) * 0.018
                 + math.sin(5 * a + self.t * 2.3) * 0.008)
            punto = QPointF(c.x() + math.cos(a) * r * (1 + d), c.y() + math.sin(a) * r * (1 - d * 0.8))
            if i == 0:
                camino.moveTo(punto)
            else:
                camino.lineTo(punto)
        camino.closeSubpath()
        return camino

    @staticmethod
    def _pintar_pompa(p: QPainter, c: QPointF, r: float, alfa: float, giro: float):
        g = QRadialGradient(c, r)
        g.setColorAt(0.0, QColor(255, 255, 255, 0))
        g.setColorAt(0.82, QColor(200, 225, 245, int(18 * alfa)))
        g.setColorAt(1.0, QColor(150, 190, 230, int(55 * alfa)))
        p.setBrush(g)
        borde = QConicalGradient(c, giro)
        for i, col in enumerate(_IRIS):
            q = QColor(col)
            q.setAlpha(int(120 * alfa))
            borde.setColorAt(i / (len(_IRIS) - 1), q)
        p.setPen(QPen(QBrush(borde), max(1.0, r * 0.05)))
        p.drawEllipse(c, r, r)
        p.setPen(QPen(QColor(255, 255, 255, int(200 * alfa)), max(1.0, r * 0.06), Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(c.x() - r * 0.72, c.y() - r * 0.72, r * 1.44, r * 1.44), 110 * 16, 45 * 16)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        caja = QRectF(self.rect()).adjusted(10, 10, -10, -10)

        # tarjeta con sombra suave
        sombra = QPainterPath()
        sombra.addRoundedRect(caja.translated(0, 4), 28, 28)
        p.fillPath(sombra, QColor(20, 50, 74, 45))
        tarjeta = QPainterPath()
        tarjeta.addRoundedRect(caja, 28, 28)
        fondo = QLinearGradient(caja.topLeft(), caja.bottomRight())
        fondo.setColorAt(0.0, QColor("#F7FBFF"))
        fondo.setColorAt(0.55, QColor("#EAF3FB"))
        fondo.setColorAt(1.0, QColor("#E4EDFA"))
        p.fillPath(tarjeta, fondo)

        # burbujas que suben por el fondo (segundo video)
        p.save()
        p.setClipPath(tarjeta)
        for b in self._pompas:
            x = b.x + math.sin(b.fase + self.t * 0.9) * b.amp
            self._pintar_pompa(p, QPointF(x, b.y), b.radio, b.alfa, b.giro + self.t * 40)
        p.restore()

        # burbuja principal con el logo (primer video)
        c = QPointF(caja.center().x(), caja.top() + 175)
        r = 118.0
        contorno = self._contorno(c, r)

        halo = QRadialGradient(c, r * 1.45)
        halo.setColorAt(0.6, QColor(127, 219, 255, 55))
        halo.setColorAt(1.0, QColor(127, 219, 255, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(c, r * 1.45, r * 1.45)

        p.save()
        p.setClipPath(contorno)
        cuerpo = QRadialGradient(c - QPointF(r * 0.2, r * 0.25), r * 1.15)
        cuerpo.setColorAt(0.0, QColor(255, 255, 255, 235))
        cuerpo.setColorAt(0.7, QColor(232, 244, 255, 220))
        cuerpo.setColorAt(1.0, QColor(205, 225, 250, 230))
        p.fillPath(contorno, cuerpo)

        if not self._logo.isNull():
            lado = r * 1.62
            destino = QRectF(c.x() - lado / 2, c.y() - lado / 2, lado, lado)
            p.setOpacity(0.16)                                   # logo «vacío»: tenue
            p.drawPixmap(destino, self._logo, QRectF(self._logo.rect()))
            p.setOpacity(1.0)
            nivel = c.y() + r - 2 * r * self.progreso            # nivel del llenado, con superficie ondulada
            agua = QPainterPath()
            agua.moveTo(c.x() - r * 1.2, c.y() + r * 1.2)
            pasos = 40
            for i in range(pasos + 1):
                x = c.x() - r * 1.2 + 2.4 * r * i / pasos
                ola = math.sin(x / 22 + self.t * 3.2) * 4.5 + math.sin(x / 13 - self.t * 2.1) * 2.0
                agua.lineTo(x, nivel + ola * (1 - self.progreso ** 6))
            agua.lineTo(c.x() + r * 1.2, c.y() + r * 1.2)
            agua.closeSubpath()
            p.save()
            p.setClipPath(agua, Qt.IntersectClip)
            p.drawPixmap(destino, self._logo, QRectF(self._logo.rect()))
            tinte = QLinearGradient(QPointF(0, nivel), QPointF(0, c.y() + r))
            tinte.setColorAt(0.0, QColor(127, 219, 255, 40))
            tinte.setColorAt(1.0, QColor(91, 140, 255, 25))
            p.fillPath(agua, tinte)
            p.restore()

        # película iridiscente moviéndose por dentro del borde
        for k, col in enumerate(("#FF8AD8", "#FFD27A", "#A77BFF", "#7FDBFF")):
            a = self.t * (0.55 + 0.12 * k) + k * 1.6
            centro = QPointF(c.x() + math.cos(a) * r * 0.78, c.y() + math.sin(a * 1.3) * r * 0.78)
            mancha = QRadialGradient(centro, r * 0.75)
            q = QColor(col)
            q.setAlpha(70)
            mancha.setColorAt(0.0, q)
            q.setAlpha(0)
            mancha.setColorAt(1.0, q)
            p.fillPath(contorno, mancha)
        p.restore()

        # borde iridiscente que gira, con resplandor
        iris = QConicalGradient(c, self.t * 35)
        for i, col in enumerate(_IRIS):
            iris.setColorAt(i / (len(_IRIS) - 1), QColor(col))
        p.setBrush(Qt.NoBrush)
        for ancho, alfa in ((14, 0.18), (7, 0.35), (2.6, 0.95)):
            p.setOpacity(alfa)
            p.setPen(QPen(QBrush(iris), ancho))
            p.drawPath(contorno)
        p.setOpacity(1.0)

        # brillos
        p.setPen(QPen(QColor(255, 255, 255, 230), 7, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(c.x() - r * 0.78, c.y() - r * 0.78, r * 1.56, r * 1.56), 112 * 16, 38 * 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 210))
        p.drawEllipse(QPointF(c.x() - r * 0.5, c.y() - r * 0.74), 5, 4)

        # textos
        y = c.y() + r + 34
        p.setPen(QColor(_TEXTO))
        p.setFont(QFont("Segoe UI", 17, QFont.DemiBold))
        p.drawText(QRectF(caja.left(), y, caja.width(), 32), Qt.AlignHCenter, "Lavandería Oceánica")
        p.setPen(QColor(_SUAVE))
        p.setFont(QFont("Segoe UI", 10))
        p.drawText(QRectF(caja.left(), y + 38, caja.width(), 22), Qt.AlignHCenter,
                   f"{self.texto}   {int(round(self.progreso * 100))} %")
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
