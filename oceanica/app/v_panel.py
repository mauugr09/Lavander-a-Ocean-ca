"""Panel del negocio (administrador): gráficas de ventas, avance del mes, clientes y servicios principales."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from PySide6.QtCharts import (QBarCategoryAxis, QBarSet, QChart, QChartView, QHorizontalBarSeries, QLineSeries,
                              QPieSeries, QStackedBarSeries, QValueAxis)
from PySide6.QtCore import QMargins, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QStackedLayout, QVBoxLayout, QWidget)

from ..servicios import panel, reportes
from . import tema
from .iconos import en_etiqueta, poner
from .util import dinero, etiqueta, seguro, tarjeta

PERIODOS = [("Este mes", "mes"), ("Últimos 3 meses", "trimestre"), ("Este año", "anio")]
COLORES_PASTEL = ["#0B3C9E", "#1AA6C8", "#7B3FA0", "#1E8E5A", "#B86E00", "#5B6F86"]


def _rango_periodo(clave: str, hoy: date) -> tuple[date, date]:
    if clave == "mes":
        return hoy.replace(day=1), hoy
    if clave == "trimestre":
        inicio = hoy.replace(day=1)
        for _ in range(2):
            inicio = (inicio - timedelta(days=1)).replace(day=1)
        return inicio, hoy
    return hoy.replace(month=1, day=1), hoy


def _f(v) -> float:
    return float(Decimal(v or 0))


def _fuente(tam: float, negrita: bool = False) -> QFont:
    f = QFont()
    f.setPointSizeF(tam)
    f.setBold(negrita)
    return f


def _nueva_grafica() -> QChart:
    g = QChart()
    g.setBackgroundVisible(False)
    g.setMargins(QMargins(4, 4, 4, 4))
    g.legend().setVisible(False)
    g.setAnimationOptions(QChart.NoAnimation)
    return g


def _eje_dinero(maximo: float) -> QValueAxis:
    eje = QValueAxis()
    eje.setRange(0, max(maximo * 1.15, 100))
    eje.setLabelFormat("$%.0f")
    eje.applyNiceNumbers()
    eje.setLabelsFont(_fuente(10))
    eje.setGridLineColor(QColor("#E3ECF4"))
    return eje


class Grafica(QFrame):
    """Tarjeta con título, subtítulo y la gráfica (o un aviso si no hay datos)."""

    def __init__(self, titulo: str, alto: int = 320):
        super().__init__()
        self.setProperty("rol", "tarjeta")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(2)
        lay.addWidget(etiqueta(titulo, "subtitulo"))
        self.sub = etiqueta("", "suave", True)
        lay.addWidget(self.sub)
        self.vista = QChartView(self)
        self.vista.setRenderHint(QPainter.Antialiasing)
        self.vista.setMinimumHeight(alto)
        self.vista.setStyleSheet("background: transparent;")
        self.vacio = etiqueta("Todavía no hay ventas en este periodo.", "suave")
        self.vacio.setParent(self)
        self.vacio.setAlignment(Qt.AlignCenter)
        self.vacio.setMinimumHeight(alto)
        self.pila = QStackedLayout()
        lay.addLayout(self.pila)  # primero se instala el contenedor: así nada se muestra como ventana suelta
        self.pila.addWidget(self.vista)
        self.pila.addWidget(self.vacio)

    def mostrar(self, grafica: QChart | None, subtitulo: str = ""):
        self.sub.setText(subtitulo)
        self.sub.setVisible(bool(subtitulo))
        if grafica is None:
            self.pila.setCurrentWidget(self.vacio)
            return
        vieja = self.vista.chart()
        self.vista.setChart(grafica)
        if vieja is not None:
            vieja.deleteLater()
        self.pila.setCurrentWidget(self.vista)


class Indicador(QFrame):
    """Cifra grande con su comparación contra el periodo anterior."""

    def __init__(self, titulo: str, comparacion: str):
        super().__init__()
        self.setProperty("rol", "tarjeta")
        self.comparacion = comparacion
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)
        lay.addWidget(etiqueta(titulo, "suave"))
        self.valor = etiqueta("—", "titulo")
        lay.addWidget(self.valor)
        fila = QHBoxLayout()
        fila.setSpacing(6)
        self.ico = QLabel(self)
        self.texto = etiqueta("")
        self.texto.setWordWrap(True)
        fila.addWidget(self.ico)
        fila.addWidget(self.texto, 1)
        lay.addLayout(fila)

    def poner(self, valor: str, variacion: Decimal | None = None, detalle: str = ""):
        self.valor.setText(valor)
        if detalle:
            self.ico.clear()
            self.texto.setStyleSheet(f"color: {tema.TEXTO_SUAVE};")
            self.texto.setText(detalle)
        elif variacion is None:
            self.ico.clear()
            self.texto.setStyleSheet(f"color: {tema.TEXTO_SUAVE};")
            self.texto.setText(f"Sin ventas {self.comparacion} para comparar")
        else:
            sube = variacion >= 0
            color = tema.OK if sube else tema.ERROR
            en_etiqueta(self.ico, "trending-up" if sube else "trending-down", color, 22)
            self.texto.setStyleSheet(f"color: {color}; font-weight: 600;")
            self.texto.setText(f"{'+' if sube else ''}{variacion}% {self.comparacion}")


class PanelView(QWidget):
    titulo = "Panel del negocio"

    def __init__(self, ctx):
        super().__init__()
        self.setObjectName("pagina")
        self.ctx = ctx
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setStyleSheet("QScrollArea { background: transparent; }")
        raiz.addWidget(area)
        cont = QWidget()
        cont.setObjectName("pagina")
        area.setWidget(cont)
        lay = QVBoxLayout(cont)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(14)

        cab = QHBoxLayout()
        textos = QVBoxLayout()
        textos.addWidget(etiqueta("Panel del negocio", "titulo"))
        textos.addWidget(etiqueta("Cómo van las ventas. Las cifras son el total de las órdenes recibidas "
                                  "(sin canceladas).", "suave", True))
        cab.addLayout(textos, 1)
        self.b_actualizar = poner(QPushButton("Actualizar"), "rotate-clockwise")
        self.b_actualizar.clicked.connect(self.al_mostrar)
        cab.addWidget(self.b_actualizar, 0, Qt.AlignTop)
        lay.addLayout(cab)

        fila_ind = QHBoxLayout()
        fila_ind.setSpacing(12)
        self.i_hoy = Indicador("Vendido hoy", "vs ayer")
        self.i_semana = Indicador("Esta semana", "vs semana anterior")
        self.i_mes = Indicador("Este mes", "vs mismos días del mes anterior")
        self.i_cobrar = Indicador("Por cobrar", "")
        for w in (self.i_hoy, self.i_semana, self.i_mes, self.i_cobrar):
            fila_ind.addWidget(w, 1)
        lay.addLayout(fila_ind)

        fila1 = QHBoxLayout()
        fila1.setSpacing(12)
        self.g_meses = Grafica("Ventas por mes (últimos 12 meses)")
        self.g_avance = Grafica("Cómo va el mes")
        fila1.addWidget(self.g_meses, 3)
        fila1.addWidget(self.g_avance, 2)
        lay.addLayout(fila1)

        fila_p = QHBoxLayout()
        fila_p.addWidget(etiqueta("Clientes, servicios y formas de pago", "subtitulo"))
        fila_p.addStretch(1)
        fila_p.addWidget(QLabel("Periodo"))
        self.periodo = QComboBox()
        self.periodo.setMinimumHeight(40)
        for texto, clave in PERIODOS:
            self.periodo.addItem(texto, clave)
        self.periodo.currentIndexChanged.connect(self._cargar_periodo)
        fila_p.addWidget(self.periodo)
        lay.addLayout(fila_p)

        rej = QGridLayout()
        rej.setSpacing(12)
        self.g_clientes = Grafica("Clientes más frecuentes", 300)
        self.g_servicios = Grafica("Servicios que más venden", 300)
        self.g_pagos = Grafica("Cómo pagan los clientes", 300)
        self.g_datos = tarjeta()
        dl = QVBoxLayout(self.g_datos)
        dl.setContentsMargins(16, 14, 16, 14)
        dl.addWidget(etiqueta("Datos del periodo", "subtitulo"))
        self.datos: dict[str, QLabel] = {}
        cuad = QGridLayout()
        cuad.setSpacing(14)
        for i, (clave, texto) in enumerate([("vendido", "Vendido"), ("ordenes", "Órdenes"),
                                            ("ticket_promedio", "Promedio por orden"), ("kilos", "Kilos lavados"),
                                            ("clientes_nuevos", "Clientes nuevos"), ("cobrado", "Cobrado")]):
            celda = QVBoxLayout()
            celda.addWidget(etiqueta(texto, "suave"))
            self.datos[clave] = etiqueta("—", "titulo")
            celda.addWidget(self.datos[clave])
            cuad.addLayout(celda, i // 2, i % 2)
        dl.addLayout(cuad)
        dl.addStretch(1)
        rej.addWidget(self.g_clientes, 0, 0)
        rej.addWidget(self.g_servicios, 0, 1)
        rej.addWidget(self.g_pagos, 1, 0)
        rej.addWidget(self.g_datos, 1, 1)
        for c in range(2):
            rej.setColumnStretch(c, 1)
        lay.addLayout(rej)
        lay.addStretch(1)

    # ------------------------------------------------------------------ datos
    def al_mostrar(self):
        hoy = date.today()
        ok, r = seguro(self, panel.resumen, self.ctx.conn, hoy)
        if ok:
            self.i_hoy.poner(dinero(r["hoy"]["vendido"]), r["hoy"]["variacion"])
            self.i_semana.poner(dinero(r["semana"]["vendido"]), r["semana"]["variacion"])
            self.i_mes.poner(dinero(r["mes"]["vendido"]), r["mes"]["variacion"])
            self.i_cobrar.poner(dinero(r["por_cobrar"]), detalle="Saldo pendiente de todas las órdenes")
        ok, meses = seguro(self, panel.ventas_por_mes, self.ctx.conn, 12, hoy)
        if ok:
            self._grafica_meses(meses)
        ok, acum = seguro(self, panel.acumulado_del_mes, self.ctx.conn, hoy)
        if ok:
            self._grafica_avance(acum)
        self._cargar_periodo()

    def _cargar_periodo(self):
        d, h = _rango_periodo(self.periodo.currentData(), date.today())
        ok, cli = seguro(self, panel.clientes_top, self.ctx.conn, d, h)
        if ok:
            self._barras_horizontales(self.g_clientes, [c["cliente"] for c in cli], [c["ordenes"] for c in cli],
                                      tema.PRIMARIO, (f"Por número de visitas. {cli[0]['cliente']} ha gastado "
                                                      f"{dinero(cli[0]['total'])} en el periodo.") if cli else "",
                                      formato="@value visitas", dinero_eje=False)
        ok, serv = seguro(self, panel.servicios_top, self.ctx.conn, d, h)
        if ok:
            self._barras_horizontales(self.g_servicios, [s["servicio"] for s in serv], [s["importe"] for s in serv],
                                      tema.SECUNDARIO, f"El que más deja: {serv[0]['servicio']}" if serv else "")
        ok, pagos = seguro(self, panel.cobros_por_metodo, self.ctx.conn, d, h)
        if ok:
            self._dona(pagos)
        ok, r = seguro(self, reportes.resumen_general, self.ctx.conn, d, h)
        if ok:
            for clave in ("vendido", "ticket_promedio", "cobrado"):
                self.datos[clave].setText(dinero(r[clave]))
            self.datos["ordenes"].setText(f"{r['ordenes']:,}")
            self.datos["clientes_nuevos"].setText(str(r["clientes_nuevos"]))
            self.datos["kilos"].setText(f"{r['kilos']:,.1f} kg")

    # --------------------------------------------------------------- gráficas
    def _grafica_meses(self, meses: list[dict]):
        mejor = panel.mejor_mes(meses)
        if mejor is None:
            self.g_meses.mostrar(None)
            return
        normal, destacado = QBarSet("Ventas"), QBarSet("Mejor mes")
        normal.setColor(QColor(tema.PRIMARIO))
        normal.setBorderColor(QColor(tema.PRIMARIO))
        destacado.setColor(QColor(tema.OK))
        destacado.setBorderColor(QColor(tema.OK))
        for m in meses:
            es = m is mejor
            normal.append(0 if es else _f(m["vendido"]))
            destacado.append(_f(m["vendido"]) if es else 0)
        serie = QStackedBarSeries()
        serie.append(normal)
        serie.append(destacado)
        serie.setBarWidth(0.6)
        g = _nueva_grafica()
        g.addSeries(serie)
        x = QBarCategoryAxis()
        x.append([panel.MESES[m["mes"].month - 1] for m in meses])
        x.setLabelsFont(_fuente(9.5))
        x.setGridLineVisible(False)
        g.addAxis(x, Qt.AlignBottom)
        serie.attachAxis(x)
        y = _eje_dinero(max(_f(m["vendido"]) for m in meses))
        g.addAxis(y, Qt.AlignLeft)
        serie.attachAxis(y)
        nombre = panel.MESES_LARGOS[mejor["mes"].month - 1]
        desde = meses[0]["mes"]
        self.g_meses.mostrar(g, f"De {panel.MESES_LARGOS[desde.month - 1]} {desde.year} a hoy. Mejor mes: {nombre} {mejor['mes'].year} con {dinero(mejor['vendido'])} "
                                f"({mejor['ordenes']} órdenes), en verde.")

    def _grafica_avance(self, a: dict):
        if not a["actual"][-1] and not a["anterior"][-1]:
            self.g_avance.mostrar(None)
            return
        g = _nueva_grafica()
        actual, anterior = QLineSeries(), QLineSeries()
        actual.setName(a["nombre_actual"].capitalize())
        anterior.setName(a["nombre_anterior"].capitalize())
        for dia, v in enumerate(a["anterior"], 1):
            anterior.append(dia, _f(v))
        for dia, v in enumerate(a["actual"], 1):
            actual.append(dia, _f(v))
        anterior.setPen(QPen(QColor("#9FB0C0"), 2, Qt.DashLine))
        actual.setPen(QPen(QColor(tema.PRIMARIO), 3.5))
        g.addSeries(anterior)
        g.addSeries(actual)
        x = QValueAxis()
        x.setRange(1, 31)
        x.setTickCount(7)
        x.setLabelFormat("%d")
        x.setTitleText("Día del mes")
        x.setLabelsFont(_fuente(9.5))
        x.setGridLineVisible(False)
        y = _eje_dinero(max(_f(a["actual"][-1]), _f(a["anterior"][-1])))
        for eje, lado in ((x, Qt.AlignBottom), (y, Qt.AlignLeft)):
            g.addAxis(eje, lado)
            actual.attachAxis(eje)
            anterior.attachAxis(eje)
        g.legend().setVisible(True)
        g.legend().setAlignment(Qt.AlignBottom)
        g.legend().setFont(_fuente(10))
        hoy = len(a["actual"])
        previo_mismo_dia = a["anterior"][min(hoy, len(a["anterior"])) - 1]
        dif = a["actual"][-1] - previo_mismo_dia
        texto = (f"Al día {hoy}: {dinero(a['actual'][-1])}, "
                 + (f"{dinero(abs(dif))} {'más' if dif >= 0 else 'menos'} que {a['nombre_anterior']} a la misma fecha."))
        self.g_avance.mostrar(g, texto)

    def _barras_horizontales(self, caja: Grafica, nombres: list[str], valores: list, color: str, subtitulo: str,
                             formato: str = "$@value", dinero_eje: bool = True):
        if not nombres:
            caja.mostrar(None)
            return
        conjunto = QBarSet("")
        conjunto.setColor(QColor(color))
        conjunto.setBorderColor(QColor(color))
        nombres, valores = nombres[::-1], valores[::-1]  # el primero arriba
        for v in valores:
            conjunto.append(_f(v))
        conjunto.setLabelColor(QColor(tema.TEXTO))
        serie = QHorizontalBarSeries()
        serie.append(conjunto)
        serie.setBarWidth(0.65)
        serie.setLabelsVisible(True)
        serie.setLabelsFormat(formato)
        serie.setLabelsPosition(QHorizontalBarSeries.LabelsOutsideEnd)
        g = _nueva_grafica()
        g.addSeries(serie)
        y = QBarCategoryAxis()
        y.append([n if len(n) <= 34 else n[:33] + "…" for n in nombres])
        y.setLabelsFont(_fuente(10))
        y.setGridLineVisible(False)
        g.addAxis(y, Qt.AlignLeft)
        serie.attachAxis(y)
        tope = max(_f(v) for v in valores)
        if dinero_eje:
            x = _eje_dinero(tope * 1.5)
        else:
            x = QValueAxis()
            x.setRange(0, tope * 1.8)
        x.setVisible(False)
        g.addAxis(x, Qt.AlignBottom)
        serie.attachAxis(x)
        caja.mostrar(g, subtitulo)

    def _dona(self, pagos: list[dict]):
        total = sum((p["total"] for p in pagos), Decimal(0))
        if not total:
            self.g_pagos.mostrar(None)
            return
        serie = QPieSeries()
        serie.setHoleSize(0.5)
        for i, p in enumerate(pagos):
            pct = p["total"] * 100 / total
            r = serie.append(f"{p['metodo']}  {pct:.0f}%", _f(p["total"]))
            r.setColor(QColor(COLORES_PASTEL[i % len(COLORES_PASTEL)]))
            r.setBorderColor(QColor("white"))
            r.setLabelFont(_fuente(10.5))
            r.setLabelVisible(True)
            r.setLabelPosition(r.LabelPosition.LabelOutside)
            r.setLabelArmLengthFactor(0.12)
        serie.setPieSize(0.62)
        g = _nueva_grafica()
        g.addSeries(serie)
        self.g_pagos.mostrar(g, f"Cobrado en el periodo: {dinero(total)}")
