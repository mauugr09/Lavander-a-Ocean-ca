"""Panel del negocio (administrador): gráficas de ventas, avance del mes, clientes y servicios principales."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QComboBox, QFrame, QGraphicsBlurEffect, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QStackedLayout, QToolButton, QVBoxLayout, QWidget)

from ..servicios import panel, reportes
from . import tema
from .graficas import Barras, BarrasHorizontales, Dona, Lineas
from .iconos import en_etiqueta, poner
from .util import dinero, etiqueta, seguro, tarjeta

PERIODOS = [("Este mes", "mes"), ("Últimos 3 meses", "trimestre"), ("Este año", "anio")]
COLORES_PAGO = ["#0B3C9E", "#1AA6C8", "#7B3FA0", "#1E8E5A", "#B86E00", "#5B6F86"]


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


class Grafica(QFrame):
    """Tarjeta con título, subtítulo y la gráfica (o un aviso si no hay datos)."""

    def __init__(self, titulo: str, alto: int = 300):
        super().__init__()
        self.setProperty("rol", "tarjeta")
        self.alto = alto
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(6)
        lay.addWidget(etiqueta(titulo, "subtitulo"))
        self.sub = etiqueta("", "suave", True)
        lay.addWidget(self.sub)
        self.pila = QStackedLayout()
        lay.addLayout(self.pila)  # primero se instala el contenedor: así nada se muestra como ventana suelta
        self.vacio = etiqueta("Todavía no hay ventas en este periodo.", "suave")
        self.vacio.setParent(self)
        self.vacio.setAlignment(Qt.AlignCenter)
        self.vacio.setMinimumHeight(alto)
        self.pila.addWidget(self.vacio)
        self.actual: QWidget | None = None

    def mostrar(self, grafica: QWidget | None, subtitulo: str = ""):
        self.sub.setText(subtitulo)
        self.sub.setVisible(bool(subtitulo))
        if self.actual is not None:
            self.pila.removeWidget(self.actual)
            self.actual.deleteLater()
            self.actual = None
        if grafica is None:
            self.pila.setCurrentWidget(self.vacio)
            return
        grafica.setParent(self)
        grafica.setMinimumHeight(max(grafica.minimumHeight(), 120))
        self.pila.addWidget(grafica)
        self.pila.setCurrentWidget(grafica)
        self.actual = grafica


class Indicador(QFrame):
    """Cifra grande con su comparación contra el periodo anterior. El ojo la muestra u oculta (borrosa)."""

    def __init__(self, titulo: str, comparacion: str, al_cambiar=None):
        super().__init__()
        self.setProperty("rol", "tarjeta")
        self.comparacion, self.al_cambiar = comparacion, al_cambiar
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 10, 12)
        lay.setSpacing(4)
        cab = QHBoxLayout()
        cab.addWidget(etiqueta(titulo, "suave"), 1)
        self.ojo = QToolButton(self)
        self.ojo.setAutoRaise(True)
        self.ojo.setCursor(Qt.PointingHandCursor)
        self.ojo.setIconSize(QSize(22, 22))
        self.ojo.setFixedSize(36, 32)
        self.ojo.setStyleSheet("QToolButton { border: none; border-radius: 6px; } "
                               "QToolButton:hover { background: #E6F0FF; }")
        self.ojo.clicked.connect(lambda: self.ocultar(not self.oculto, avisar=True))
        cab.addWidget(self.ojo, 0, Qt.AlignTop)
        lay.addLayout(cab)
        self.contenido = QWidget(self)
        cl = QVBoxLayout(self.contenido)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        self.valor = etiqueta("—", "titulo")
        cl.addWidget(self.valor)
        fila = QHBoxLayout()
        fila.setSpacing(6)
        self.ico = QLabel(self.contenido)
        self.texto = etiqueta("")
        self.texto.setWordWrap(True)
        fila.addWidget(self.ico)
        fila.addWidget(self.texto, 1)
        cl.addLayout(fila)
        lay.addWidget(self.contenido)
        self.oculto = False
        self.ocultar(True)

    def ocultar(self, oculto: bool, avisar: bool = False):
        """Oculto = cifras borrosas, para que no las lea quien está frente al mostrador."""
        self.oculto = oculto
        if oculto:
            efecto = QGraphicsBlurEffect(self.contenido)
            efecto.setBlurRadius(32)
            self.contenido.setGraphicsEffect(efecto)
        else:
            self.contenido.setGraphicsEffect(None)
        poner(self.ojo, "eye" if oculto else "eye-off", tema.TEXTO_SUAVE, 22)
        self.ojo.setText("")
        self.ojo.setToolTip("Mostrar la cifra" if oculto else "Ocultar la cifra")
        if avisar and self.al_cambiar:
            self.al_cambiar()

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
        self.b_ver = poner(QPushButton("Mostrar cifras"), "eye")
        self.b_ver.clicked.connect(self._alternar_todo)
        cab.addWidget(self.b_ver, 0, Qt.AlignTop)
        self.b_actualizar = poner(QPushButton("Actualizar"), "rotate-clockwise")
        self.b_actualizar.clicked.connect(self.cargar)
        cab.addWidget(self.b_actualizar, 0, Qt.AlignTop)
        lay.addLayout(cab)

        fila_ind = QHBoxLayout()
        fila_ind.setSpacing(12)
        self.i_hoy = Indicador("Vendido hoy", "vs ayer", self._estado_ojos)
        self.i_semana = Indicador("Esta semana", "vs semana anterior", self._estado_ojos)
        self.i_mes = Indicador("Este mes", "vs mismos días del mes anterior", self._estado_ojos)
        self.i_cobrar = Indicador("Por cobrar", "", self._estado_ojos)
        self.indicadores = [self.i_hoy, self.i_semana, self.i_mes, self.i_cobrar]
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
        self.g_clientes = Grafica("Clientes más frecuentes", 280)
        self.g_servicios = Grafica("Servicios que más venden", 280)
        self.g_pagos = Grafica("Cómo pagan los clientes", 260)
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
    def _estado_ojos(self):
        todos_visibles = all(not i.oculto for i in self.indicadores)
        self.b_ver.setText("Ocultar cifras" if todos_visibles else "Mostrar cifras")
        poner(self.b_ver, "eye-off" if todos_visibles else "eye")

    def _alternar_todo(self):
        ocultar = all(not i.oculto for i in self.indicadores)
        for i in self.indicadores:
            i.ocultar(ocultar)
        self._estado_ojos()

    def ocultar_cifras(self):
        """Cada vez que se entra al panel, las cifras empiezan ocultas."""
        for i in self.indicadores:
            i.ocultar(True)
        self._estado_ojos()

    def al_mostrar(self):
        self.ocultar_cifras()
        self.cargar()

    def cargar(self):
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
            self._clientes(cli)
        ok, serv = seguro(self, panel.servicios_top, self.ctx.conn, d, h)
        if ok:
            self._servicios(serv)
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
        etiquetas = [panel.MESES[m["mes"].month - 1] for m in meses]
        detalles = [f"{panel.MESES_LARGOS[m['mes'].month - 1].capitalize()} {m['mes'].year}: "
                    f"{dinero(m['vendido'])} en {m['ordenes']} órdenes" for m in meses]
        g = Barras(etiquetas, [_f(m["vendido"]) for m in meses], detalles, meses.index(mejor))
        nombre = panel.MESES_LARGOS[mejor["mes"].month - 1]
        desde = meses[0]["mes"]
        self.g_meses.mostrar(g, f"De {panel.MESES_LARGOS[desde.month - 1]} {desde.year} a hoy. Mejor mes: "
                                f"{nombre} {mejor['mes'].year} con {dinero(mejor['vendido'])} "
                                f"({mejor['ordenes']} órdenes), en verde.")

    def _grafica_avance(self, a: dict):
        if not a["actual"][-1] and not a["anterior"][-1]:
            self.g_avance.mostrar(None)
            return
        g = Lineas([(a["nombre_anterior"].capitalize(), [_f(v) for v in a["anterior"]], "#9FB0C0", True),
                    (a["nombre_actual"].capitalize(), [_f(v) for v in a["actual"]], tema.PRIMARIO, False)])
        hoy = len(a["actual"])
        previo = a["anterior"][min(hoy, len(a["anterior"])) - 1]
        dif = a["actual"][-1] - previo
        self.g_avance.mostrar(g, f"Al día {hoy}: {dinero(a['actual'][-1])}, {dinero(abs(dif))} "
                                 f"{'más' if dif >= 0 else 'menos'} que {a['nombre_anterior']} a la misma fecha.")

    def _clientes(self, cli: list[dict]):
        if not cli:
            self.g_clientes.mostrar(None)
            return
        items = [(c["cliente"], c["ordenes"], f"{c['ordenes']} visitas",
                  f"{c['cliente']}: {c['ordenes']} visitas, {dinero(c['total'])} gastados") for c in cli]
        self.g_clientes.mostrar(BarrasHorizontales(items, tema.PRIMARIO),
                                f"Por número de visitas. {cli[0]['cliente']} ha gastado {dinero(cli[0]['total'])} "
                                "en el periodo. Pase el mouse sobre un nombre para ver lo que gastó.")

    def _servicios(self, serv: list[dict]):
        if not serv:
            self.g_servicios.mostrar(None)
            return
        items = []
        for s_ in serv:
            cant = f"{s_['cantidad']:,.1f} kg" if s_["unidad"] == "kilo" else f"{int(s_['cantidad'])} piezas"
            items.append((s_["servicio"], _f(s_["importe"]), dinero(s_["importe"]), f"{s_['servicio']}: {cant}"))
        self.g_servicios.mostrar(BarrasHorizontales(items, tema.SECUNDARIO),
                                 f"El que más deja: {serv[0]['servicio']}")

    def _dona(self, pagos: list[dict]):
        total = sum((p["total"] for p in pagos), Decimal(0))
        if not total:
            self.g_pagos.mostrar(None)
            return
        items = [(p["metodo"], _f(p["total"]), COLORES_PAGO[i % len(COLORES_PAGO)]) for i, p in enumerate(pagos)]
        self.g_pagos.mostrar(Dona(items), f"Cobrado en el periodo: {dinero(total)}")
