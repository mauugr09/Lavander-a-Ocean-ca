"""Gráficas dibujadas a mano con QPainter (solo QtGui/QtWidgets, incluidos en cualquier instalación de PySide6).

No dependen de Qt Charts (PySide6-Addons), así que funcionan igual en todas las computadoras del equipo
y en el ejecutable. Cada gráfica muestra el valor exacto al pasar el mouse.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from . import tema

REJILLA = QColor("#E3ECF4")
EJE = QColor("#B9C4D2")
TEXTO = QColor(tema.TEXTO)
SUAVE = QColor(tema.TEXTO_SUAVE)


def pesos(v: float) -> str:
    return f"${v:,.0f}"


def escala(maximo: float, pasos: int = 4) -> tuple[float, float]:
    """(tope, paso) redondos para el eje: 34,882 -> (40,000, 10,000)."""
    if maximo <= 0:
        return 100.0, 25.0
    bruto = maximo / pasos
    potencia = 10 ** math.floor(math.log10(bruto))
    for m in (1, 2, 2.5, 5, 10):
        paso = m * potencia
        if paso * pasos >= maximo:
            return paso * pasos, paso
    return 10 * potencia * pasos, 10 * potencia


def _fuente(base: QFont, tam: float, negrita: bool = False) -> QFont:
    f = QFont(base)
    f.setPointSizeF(tam)
    f.setBold(negrita)
    return f


class _Base(QWidget):
    def __init__(self, alto: int):
        super().__init__()
        self.setMinimumHeight(alto)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.zonas: list[tuple[QRectF, str]] = []   # rectángulo -> texto del globo de ayuda

    def mouseMoveEvent(self, e):
        p = e.position()
        texto = next((t for r, t in self.zonas if r.contains(p)), "")
        if texto:
            QToolTip.showText(e.globalPosition().toPoint(), texto, self)
        else:
            QToolTip.hideText()

    def _eje_y(self, p: QPainter, area: QRectF, tope: float, paso: float, formato=pesos):
        p.setFont(_fuente(self.font(), 9.5))
        fm = QFontMetrics(p.font())
        v = 0.0
        while v <= tope + 1e-9:
            y = area.bottom() - area.height() * v / tope
            p.setPen(QPen(REJILLA if v else EJE, 1))
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            p.setPen(SUAVE)
            t = formato(v)
            p.drawText(QRectF(0, y - fm.height() / 2, area.left() - 8, fm.height()), Qt.AlignRight | Qt.AlignVCenter, t)
            v += paso


class Barras(_Base):
    """Barras verticales; la barra `destacada` va en otro color (por ejemplo, el mejor mes)."""

    def __init__(self, etiquetas: list[str], valores: list[float], detalles: list[str] | None = None,
                 destacada: int | None = None, alto: int = 300):
        super().__init__(alto)
        self.etiquetas, self.valores, self.destacada = etiquetas, valores, destacada
        self.detalles = detalles or [f"{e}: {pesos(v)}" for e, v in zip(etiquetas, valores)]

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        tope, paso = escala(max(self.valores) if self.valores else 0)
        fm = QFontMetrics(_fuente(self.font(), 9.5))
        izq = fm.horizontalAdvance(pesos(tope)) + 14
        area = QRectF(izq, 10, self.width() - izq - 6, self.height() - 10 - fm.height() - 12)
        self._eje_y(p, area, tope, paso)
        n = max(len(self.valores), 1)
        ancho = area.width() / n
        self.zonas = []
        for i, (e, v) in enumerate(zip(self.etiquetas, self.valores)):
            h = area.height() * v / tope if tope else 0
            r = QRectF(area.left() + i * ancho + ancho * 0.18, area.bottom() - h, ancho * 0.64, h)
            color = QColor(tema.OK if i == self.destacada else tema.PRIMARIO)
            camino = QPainterPath()
            camino.addRoundedRect(r, 3, 3)
            p.fillPath(camino, color)
            p.fillRect(QRectF(r.left(), r.bottom() - min(3, h), r.width(), min(3, h)), color)
            p.setPen(SUAVE if i != self.destacada else QColor(tema.OK))
            p.setFont(_fuente(self.font(), 9.5, i == self.destacada))
            p.drawText(QRectF(area.left() + i * ancho, area.bottom() + 6, ancho, fm.height() + 4), Qt.AlignCenter, e)
            self.zonas.append((QRectF(area.left() + i * ancho, area.top(), ancho, area.height()), self.detalles[i]))
        p.end()


class Lineas(_Base):
    """Varias líneas sobre los días del mes (eje X de 1 a 31). series: [(nombre, valores, color, punteada)]."""

    def __init__(self, series: list[tuple[str, list[float], str, bool]], alto: int = 300):
        super().__init__(alto)
        self.series = series

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        maximo = max((max(v) for _, v, _, _ in self.series if v), default=0)
        tope, paso = escala(maximo)
        fm = QFontMetrics(_fuente(self.font(), 9.5))
        izq = fm.horizontalAdvance(pesos(tope)) + 14
        leyenda = fm.height() + 14
        area = QRectF(izq, 10, self.width() - izq - 12, self.height() - 10 - fm.height() - 12 - leyenda)
        self._eje_y(p, area, tope, paso)
        dias = 31

        def punto(dia, v):
            return QPointF(area.left() + area.width() * (dia - 1) / (dias - 1), area.bottom() - area.height() * v / tope)

        p.setFont(_fuente(self.font(), 9.5))
        p.setPen(SUAVE)
        for dia in (1, 5, 10, 15, 20, 25, 31):
            x = punto(dia, 0).x()
            p.drawText(QRectF(x - 20, area.bottom() + 6, 40, fm.height() + 4), Qt.AlignCenter, str(dia))
        self.zonas = []
        for nombre, valores, color, punteada in self.series:
            if not valores:
                continue
            camino = QPainterPath(punto(1, valores[0]))
            for dia, v in enumerate(valores[1:], 2):
                camino.lineTo(punto(dia, v))
            p.setPen(QPen(QColor(color), 2 if punteada else 3.5, Qt.DashLine if punteada else Qt.SolidLine,
                          Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(camino)
            if not punteada:
                fin = punto(len(valores), valores[-1])
                p.setBrush(QColor(color))
                p.drawEllipse(fin, 4.5, 4.5)
                p.setBrush(Qt.NoBrush)
            for dia, v in enumerate(valores, 1):
                c = punto(dia, v)
                self.zonas.append((QRectF(c.x() - 6, area.top(), 12, area.height()),
                                   f"{nombre}, día {dia}: {pesos(v)} acumulado"))
        # leyenda
        x = area.left()
        y = self.height() - leyenda / 2 - 2
        for nombre, _, color, punteada in self.series:
            p.setPen(QPen(QColor(color), 2 if punteada else 3.5, Qt.DashLine if punteada else Qt.SolidLine))
            p.drawLine(QPointF(x, y), QPointF(x + 24, y))
            p.setPen(TEXTO)
            p.drawText(QPointF(x + 30, y + fm.ascent() / 2 - 1), nombre)
            x += 30 + fm.horizontalAdvance(nombre) + 26
        p.end()


class BarrasHorizontales(_Base):
    """Una fila por elemento: nombre, barra y valor. items: [(nombre, valor, texto_valor, ayuda)]."""

    def __init__(self, items: list[tuple[str, float, str, str]], color: str, alto_fila: int = 34):
        super().__init__(max(len(items), 1) * alto_fila + 8)
        self.items, self.color, self.alto_fila = items, color, alto_fila

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(_fuente(self.font(), 10.5))
        fm = QFontMetrics(p.font())
        nombres_w = min(max((fm.horizontalAdvance(n) for n, *_ in self.items), default=0) + 12, self.width() * 0.42)
        textos_w = max((fm.horizontalAdvance(t) for _, _, t, _ in self.items), default=0) + 12
        barra_max = max(self.width() - nombres_w - textos_w - 4, 20)
        tope = max((v for _, v, _, _ in self.items), default=0) or 1
        self.zonas = []
        for i, (nombre, v, texto, ayuda) in enumerate(self.items):
            y = 4 + i * self.alto_fila
            fila = QRectF(0, y, self.width(), self.alto_fila)
            p.setPen(TEXTO)
            p.drawText(QRectF(0, y, nombres_w - 10, self.alto_fila), Qt.AlignRight | Qt.AlignVCenter,
                       fm.elidedText(nombre, Qt.ElideRight, int(nombres_w - 10)))
            largo = max(barra_max * v / tope, 3)
            r = QRectF(nombres_w, y + self.alto_fila * 0.2, largo, self.alto_fila * 0.6)
            camino = QPainterPath()
            camino.addRoundedRect(r, 3, 3)
            p.fillPath(camino, QColor(self.color))
            p.setPen(SUAVE)
            p.drawText(QRectF(r.right() + 6, y, textos_w, self.alto_fila), Qt.AlignLeft | Qt.AlignVCenter, texto)
            self.zonas.append((fila, ayuda))
        p.end()


class Dona(_Base):
    """Gráfica de dona con su leyenda a la derecha. items: [(nombre, valor, color)]."""

    def __init__(self, items: list[tuple[str, float, str]], alto: int = 260):
        super().__init__(alto)
        self.items = items

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        total = sum(v for _, v, _ in self.items) or 1
        lado = min(self.height() - 16, self.width() * 0.48)
        r = QRectF(8, (self.height() - lado) / 2, lado, lado)
        grosor = lado * 0.22
        inicio = 90 * 16
        for nombre, v, color in self.items:
            ang = -int(round(360 * 16 * v / total))
            p.setPen(QPen(QColor(color), grosor, Qt.SolidLine, Qt.FlatCap))
            p.drawArc(r.adjusted(grosor / 2, grosor / 2, -grosor / 2, -grosor / 2), inicio, ang)
            inicio += ang
        p.setFont(_fuente(self.font(), 11))
        fm = QFontMetrics(p.font())
        x = r.right() + 24
        alto = fm.height() * 2 + 10
        y = (self.height() - alto * len(self.items)) / 2
        self.zonas = []
        for nombre, v, color in self.items:
            p.setBrush(QColor(color))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(x, y + 4, 14, 14), 3, 3)
            p.setPen(TEXTO)
            p.setFont(_fuente(self.font(), 11, True))
            p.drawText(QPointF(x + 22, y + fm.ascent() + 2), f"{nombre}  {v * 100 / total:.0f}%")
            p.setFont(_fuente(self.font(), 10.5))
            p.setPen(SUAVE)
            p.drawText(QPointF(x + 22, y + fm.ascent() + fm.height() + 4), pesos(v))
            self.zonas.append((QRectF(x, y, self.width() - x, alto), f"{nombre}: {pesos(v)}"))
            y += alto
        p.setBrush(Qt.NoBrush)
        p.end()
