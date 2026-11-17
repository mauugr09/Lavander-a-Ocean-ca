"""Burbujas que suben lentamente por el fondo de la pantalla de entrada (decorativo y discreto).

Se dibujan con QPainter detrás del contenido; la animación solo corre mientras la pantalla está visible.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PySide6.QtCore import QObject, QPointF, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient

CUADROS_POR_SEGUNDO = 30


@dataclass
class Burbuja:
    x: float
    y: float
    radio: float
    velocidad: float      # píxeles por cuadro
    fase: float           # para el vaivén lateral
    amplitud: float
    opacidad: float


class Burbujas(QObject):
    def __init__(self, widget, cantidad: int = 26):
        super().__init__(widget)
        self.widget, self.cantidad = widget, cantidad
        self.lista: list[Burbuja] = []
        self.cuadro = 0
        self.timer = QTimer(self)
        self.timer.setInterval(1000 // CUADROS_POR_SEGUNDO)
        self.timer.timeout.connect(self._avanzar)

    def _nueva(self, abajo: bool) -> Burbuja:
        w, h = max(self.widget.width(), 400), max(self.widget.height(), 300)
        radio = random.choice([random.uniform(6, 16)] * 3 + [random.uniform(18, 46)])
        return Burbuja(
            # a los lados, para no pasar sobre el logo ni el recuadro de entrada
            x=random.uniform(0, w * 0.3) if random.random() < 0.5 else random.uniform(w * 0.7, w),
            y=h + radio + random.uniform(0, h * 0.3) if abajo else random.uniform(0, h),
            radio=radio,
            velocidad=random.uniform(0.35, 1.1) * (1.25 if radio < 16 else 1.0),
            fase=random.uniform(0, math.tau),
            amplitud=random.uniform(6, 22),
            opacidad=random.uniform(0.35, 0.8),
        )

    def iniciar(self):
        if not self.lista:
            self.lista = [self._nueva(abajo=False) for _ in range(self.cantidad)]
        self.timer.start()

    def detener(self):
        self.timer.stop()

    def _avanzar(self):
        self.cuadro += 1
        for i, b in enumerate(self.lista):
            b.y -= b.velocidad
            if b.y < -b.radio * 2:
                self.lista[i] = self._nueva(abajo=True)
        self.widget.update()

    def pintar(self, p: QPainter):
        p.setRenderHint(QPainter.Antialiasing)
        for b in self.lista:
            x = b.x + math.sin(b.fase + self.cuadro / 45) * b.amplitud
            centro = QPointF(x, b.y)
            # cuerpo: casi transparente al centro y más azul en el borde, como una pompa de jabón
            g = QRadialGradient(centro, b.radio)
            g.setColorAt(0.0, QColor(255, 255, 255, int(20 * b.opacidad)))
            g.setColorAt(0.75, QColor(26, 166, 200, int(40 * b.opacidad)))
            g.setColorAt(1.0, QColor(11, 60, 158, int(70 * b.opacidad)))
            p.setBrush(g)
            p.setPen(QPen(QColor(26, 166, 200, int(110 * b.opacidad)), 1.2))
            p.drawEllipse(centro, b.radio, b.radio)
            # brillo
            p.setPen(QPen(QColor(255, 255, 255, 0)))
            p.setBrush(QColor(255, 255, 255, int(200 * b.opacidad)))
            r = b.radio * 0.22
            p.drawEllipse(QPointF(x - b.radio * 0.38, b.y - b.radio * 0.38), r, r * 0.75)
