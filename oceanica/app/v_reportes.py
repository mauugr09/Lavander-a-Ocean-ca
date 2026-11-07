"""Reportes y tablero de indicadores, con exportación a Excel y PDF (administrador)."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QComboBox, QDateEdit, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..servicios import exportacion, reportes
from .util import crear_tabla, dinero, etiqueta, seguro, tarjeta

# (título, función, ¿usa rango de fechas?, ¿pide la sesión?)
REPORTES = [
    ("Ventas por día", reportes.ventas_por_dia, True, False),
    ("Cobros por método de pago", reportes.cobros_por_metodo, True, False),
    ("Ventas por servicio", reportes.ventas_por_servicio, True, False),
    ("Órdenes pendientes", reportes.ordenes_pendientes, False, False),
    ("Clientes frecuentes", reportes.clientes_frecuentes, False, False),
    ("Insumos bajo el mínimo", reportes.insumos_bajos, False, False),
    ("Asistencia", reportes.asistencia, True, False),
    ("Cortes de caja", reportes.cortes_de_caja, True, False),
    ("Órdenes por facturar", reportes.por_facturar, True, True),
]
PERIODOS = ["Hoy", "Ayer", "Esta semana", "Este mes", "Mes pasado", "Personalizado"]
NUMERICOS = {"dinero", "numero"}


def rango_periodo(nombre: str, hoy: date | None = None) -> tuple[date, date]:
    hoy = hoy or date.today()
    if nombre == "Ayer":
        return hoy - timedelta(days=1), hoy - timedelta(days=1)
    if nombre == "Esta semana":
        return hoy - timedelta(days=hoy.weekday()), hoy
    if nombre == "Este mes":
        return hoy.replace(day=1), hoy
    if nombre == "Mes pasado":
        fin = hoy.replace(day=1) - timedelta(days=1)
        return fin.replace(day=1), fin
    return hoy, hoy


class ReportesView(QWidget):
    titulo = "Reportes"

    def __init__(self, ctx):
        super().__init__()
        self.setObjectName("pagina")
        self.ctx = ctx
        self.reporte: dict | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        lay.addWidget(etiqueta("Reportes", "titulo"))

        fila = QHBoxLayout()
        self.periodo = QComboBox()
        self.periodo.addItems(PERIODOS)
        self.periodo.setCurrentText("Este mes")
        self.desde, self.hasta = QDateEdit(), QDateEdit()
        for d in (self.desde, self.hasta):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd/MM/yyyy")
        fila.addWidget(etiqueta("Periodo"))
        fila.addWidget(self.periodo)
        fila.addWidget(self.desde)
        fila.addWidget(etiqueta("a"))
        fila.addWidget(self.hasta)
        fila.addStretch(1)
        lay.addLayout(fila)

        # indicadores del periodo
        rejilla = QGridLayout()
        rejilla.setSpacing(10)
        self.kpi: dict[str, QLabel] = {}
        for i, (clave, texto) in enumerate([("vendido", "Vendido"), ("cobrado", "Cobrado"), ("ordenes", "Órdenes"),
                                            ("ticket_promedio", "Ticket promedio"), ("kilos", "Kilos lavados"),
                                            ("por_cobrar", "Por cobrar (total)")]):
            c = tarjeta()
            cl = QVBoxLayout(c)
            cl.setContentsMargins(12, 8, 12, 8)
            cl.addWidget(etiqueta(texto, "suave"))
            valor = etiqueta("—", "subtitulo")
            f = QFont(valor.font())
            f.setPointSize(16)
            f.setBold(True)
            valor.setFont(f)
            cl.addWidget(valor)
            self.kpi[clave] = valor
            rejilla.addWidget(c, 0, i)
        lay.addLayout(rejilla)
        self.lb_alerta = etiqueta("", "suave")
        lay.addWidget(self.lb_alerta)

        fila2 = QHBoxLayout()
        self.selector = QComboBox()
        for t, *_ in REPORTES:
            self.selector.addItem(t)
        self.b_exportar = QPushButton("Exportar a Excel / PDF")
        self.b_exportar.setProperty("rol", "primario")
        fila2.addWidget(etiqueta("Reporte", "subtitulo"))
        fila2.addWidget(self.selector, 1)
        fila2.addWidget(self.b_exportar)
        lay.addLayout(fila2)
        self.lb_sub = etiqueta("", "suave")
        lay.addWidget(self.lb_sub)
        self.tabla = QTableWidget(0, 0)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setShowGrid(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.verticalHeader().setDefaultSectionSize(32)
        self.tabla.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        lay.addWidget(self.tabla, 1)

        self.periodo.currentTextChanged.connect(self._cambio_periodo)
        self.desde.dateChanged.connect(self.recargar)
        self.hasta.dateChanged.connect(self.recargar)
        self.selector.currentIndexChanged.connect(self.recargar)
        self.b_exportar.clicked.connect(self.exportar)
        self._cambio_periodo(self.periodo.currentText(), recargar=False)

    def al_mostrar(self):
        self.recargar()

    def _cambio_periodo(self, nombre: str, recargar: bool = True):
        libre = nombre == "Personalizado"
        self.desde.setEnabled(libre)
        self.hasta.setEnabled(libre)
        if not libre:
            d, h = rango_periodo(nombre)
            for w, v in ((self.desde, d), (self.hasta, h)):
                w.blockSignals(True)
                w.setDate(QDate(v.year, v.month, v.day))
                w.blockSignals(False)
        if recargar:
            self.recargar()

    def _rango(self) -> tuple[date, date]:
        return self.desde.date().toPython(), self.hasta.date().toPython()

    def recargar(self):
        d, h = self._rango()
        if d > h:
            self.lb_sub.setText("La fecha inicial no puede ser posterior a la final.")
            return
        ok, r = seguro(self, reportes.resumen_general, self.ctx.conn, d, h)
        if ok:
            self.kpi["vendido"].setText(dinero(r["vendido"]))
            self.kpi["cobrado"].setText(dinero(r["cobrado"]))
            self.kpi["ordenes"].setText(str(r["ordenes"]))
            self.kpi["ticket_promedio"].setText(dinero(r["ticket_promedio"]))
            self.kpi["kilos"].setText(f"{r['kilos']:,.1f} kg")
            self.kpi["por_cobrar"].setText(dinero(r["por_cobrar"]))
            self.lb_alerta.setText(f"{r['ordenes_abiertas']} orden(es) abiertas, {r['ordenes_retrasadas']} con entrega vencida · "
                                   f"{r['clientes_nuevos']} cliente(s) nuevos en el periodo")
        _, fn, usa_rango, usa_sesion = REPORTES[self.selector.currentIndex()]
        args = ((self.ctx.admin,) if usa_sesion else ()) + ((d, h) if usa_rango else ())
        ok, rep = seguro(self, fn, self.ctx.conn, *args)
        if ok:
            self.reporte = rep
            self._pintar(rep)

    def _pintar(self, rep: dict):
        cols, filas, totales = rep["columnas"], rep["filas"], rep["totales"]
        self.lb_sub.setText(rep["subtitulo"] + ("" if filas else "  ·  Sin datos en este periodo"))
        self.tabla.clear()
        self.tabla.setColumnCount(len(cols))
        self.tabla.setHorizontalHeaderLabels([c[1] for c in cols])
        self.tabla.setRowCount(len(filas) + (1 if totales and filas else 0))
        for r, f in enumerate(filas):
            for c, (clave, _, tipo) in enumerate(cols):
                it = QTableWidgetItem(exportacion.formatear(f.get(clave), tipo))
                if tipo in NUMERICOS:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabla.setItem(r, c, it)
        if totales and filas:
            r = len(filas)
            for c, (clave, _, tipo) in enumerate(cols):
                it = QTableWidgetItem("TOTAL" if c == 0 else (exportacion.formatear(totales[clave], tipo) if clave in totales else ""))
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter if tipo in NUMERICOS else Qt.AlignLeft | Qt.AlignVCenter)
                f = it.font()
                f.setBold(True)
                it.setFont(f)
                self.tabla.setItem(r, c, it)
        h = self.tabla.horizontalHeader()
        ancho = len(cols) > 8  # reportes anchos (por facturar): cada columna a su contenido, con barra horizontal
        for i in range(len(cols)):
            h.setSectionResizeMode(i, QHeaderView.Stretch if i == 0 and not ancho else QHeaderView.ResizeToContents)

    def exportar(self):
        if not self.reporte:
            return
        base = f"{self.reporte['titulo']} {date.today():%Y-%m-%d}".replace(" ", "_")
        ruta, filtro = QFileDialog.getSaveFileName(self, "Exportar reporte", str(date.today().strftime(base)),
                                                   "Excel (*.xlsx);;PDF (*.pdf)")
        if not ruta:
            return
        if not ruta.lower().endswith((".xlsx", ".pdf")):
            ruta += ".pdf" if "PDF" in filtro else ".xlsx"
        ok, destino = seguro(self, exportacion.exportar, self.reporte, ruta, self.ctx.nombre_negocio)
        if ok:
            if QMessageBox.question(self, "Reporte exportado", f"Guardado en:\n{destino}\n\n¿Abrirlo ahora?") == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(destino)))
