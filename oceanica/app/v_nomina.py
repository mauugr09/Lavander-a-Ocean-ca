"""Nómina semanal (administrador): calcular, revisar, aprobar, pagar y entregar recibo firmado."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox,
                               QPushButton, QRadioButton, QVBoxLayout, QWidget)

from ..config import RAIZ
from ..servicios import nomina, tickets
from . import tema
from .dialogos import _botones
from .util import a_decimal, chip, crear_tabla, dinero, etiqueta, id_seleccionado, numero, poblar, seguro

CONCEPTOS = [("Bono", "BONO"), ("Otra percepción", "OTRAPERC"), ("Descuento manual", "DESCMAN")]
ESTADO_PERIODO = {"abierto": "Abierta", "aprobado": "Aprobada", "cerrado": "Cerrada"}
PASOS = {"abierto": "Paso 1: calcula la semana y revisa los avisos.  Paso 2: aprueba cuando todo esté bien.",
         "aprobado": "Paso 3: paga a cada empleado y márcalo.  Paso 4: cuando todos estén pagados, cierra la semana.",
         "cerrado": "Semana cerrada: ya no se puede modificar. Aún puedes imprimir recibos."}


def _fmt(d: date) -> str:
    return d.strftime("%d/%m")


class ConceptoDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Agregar bono o descuento")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.tipo = QComboBox()
        for texto, clave in CONCEPTOS:
            self.tipo.addItem(texto, clave)
        self.monto, self.descripcion = QLineEdit(), QLineEdit()
        self.descripcion.setPlaceholderText("Motivo (obligatorio)")
        form.addRow("Tipo", self.tipo)
        form.addRow("Monto $", self.monto)
        form.addRow("Motivo", self.descripcion)
        lay.addLayout(form)
        bb = _botones(self, "Agregar")
        bb.accepted.connect(self._validar)
        lay.addWidget(bb)
        self.monto.setFocus()

    def _validar(self):
        m = a_decimal(self.monto.text())
        if m is None or m <= 0 or not self.descripcion.text().strip():
            QMessageBox.warning(self, "Oceánica", "Escribe un monto mayor que cero y el motivo.")
            return
        self.accept()


class PagoDialog(QDialog):
    def __init__(self, parent, empleado: str, neto):
        super().__init__(parent)
        self.setWindowTitle("Pagar nómina")
        self.setMinimumWidth(400)
        lay = QVBoxLayout(self)
        lay.addWidget(etiqueta(f"{empleado}: {dinero(neto)}", "subtitulo"))
        self.r_efectivo = QRadioButton("Efectivo (sale de la caja abierta)")
        self.r_transf = QRadioButton("Transferencia (no mueve la caja)")
        self.r_efectivo.setChecked(True)
        self.firmado = QCheckBox("Ya firmó su recibo")
        for w in (self.r_efectivo, self.r_transf, self.firmado):
            lay.addWidget(w)
        lay.addWidget(_botones(self, "Registrar pago"))

    @property
    def metodo(self) -> str:
        return "efectivo" if self.r_efectivo.isChecked() else "transferencia"


class NominaView(QWidget):
    titulo = "Nómina"

    def __init__(self, ctx):
        super().__init__()
        self.setObjectName("pagina")
        self.ctx = ctx
        self.periodo: dict | None = None
        self.nominas: dict[int, dict] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)
        lay.addWidget(etiqueta("Nómina semanal", "titulo"))
        lay.addWidget(etiqueta("Control interno de pagos: se paga por día trabajado. No calcula impuestos ni IMSS.", "suave", True))

        fila = QHBoxLayout()
        self.selector = QComboBox()
        self.selector.setMinimumWidth(260)
        self.chip_estado = etiqueta("")
        self.b_semana = QPushButton("Abrir semana…")
        fila.addWidget(etiqueta("Semana", "subtitulo"))
        fila.addWidget(self.selector)
        fila.addWidget(self.chip_estado)
        fila.addStretch(1)
        fila.addWidget(self.b_semana)
        lay.addLayout(fila)
        self.lb_pasos = etiqueta("", "suave", True)
        lay.addWidget(self.lb_pasos)

        acciones = QHBoxLayout()
        self.b_calcular = QPushButton("Calcular semana")
        self.b_calcular.setProperty("rol", "primario")
        self.b_aprobar = QPushButton("Aprobar")
        self.b_reabrir = QPushButton("Reabrir")
        self.b_cerrar = QPushButton("Cerrar semana")
        for b in (self.b_calcular, self.b_aprobar, self.b_reabrir, self.b_cerrar):
            acciones.addWidget(b)
        acciones.addStretch(1)
        self.lb_total = etiqueta("", "subtitulo")
        acciones.addWidget(self.lb_total)
        lay.addLayout(acciones)

        self.tabla = crear_tabla(["Empleado", "Días", "Percepciones", "Deducciones", "Neto a pagar", "Pago"], derecha=(1, 2, 3, 4))
        self.tabla.setMinimumHeight(170)
        lay.addWidget(self.tabla, 2)

        fila2 = QHBoxLayout()
        self.b_pagar = QPushButton("Pagar…")
        self.b_pagar.setProperty("rol", "primario")
        self.b_recibo = QPushButton("Recibo (PDF)")
        self.b_firmado = QPushButton("Marcar recibo firmado")
        self.b_concepto = QPushButton("Agregar bono / descuento")
        self.b_quitar = QPushButton("Quitar concepto")
        for b in (self.b_pagar, self.b_recibo, self.b_firmado):
            fila2.addWidget(b)
        fila2.addStretch(1)
        fila2.addWidget(self.b_concepto)
        fila2.addWidget(self.b_quitar)
        lay.addLayout(fila2)
        self.detalle = crear_tabla(["Concepto", "Detalle", "Monto"], derecha=(2,), estirar=1)
        self.detalle.setMinimumHeight(120)
        lay.addWidget(self.detalle, 1)

        self.selector.currentIndexChanged.connect(self.cargar)
        self.tabla.itemSelectionChanged.connect(self._pintar_detalle)
        self.b_semana.clicked.connect(self.abrir_semana)
        self.b_calcular.clicked.connect(self.calcular)
        self.b_aprobar.clicked.connect(self.aprobar)
        self.b_reabrir.clicked.connect(self.reabrir)
        self.b_cerrar.clicked.connect(self.cerrar)
        self.b_pagar.clicked.connect(self.pagar)
        self.b_recibo.clicked.connect(self.recibo)
        self.b_firmado.clicked.connect(self.firmado)
        self.b_concepto.clicked.connect(self.agregar_concepto)
        self.b_quitar.clicked.connect(self.quitar_concepto)

    # -------------------------------------------------------------- datos
    def al_mostrar(self):
        self.recargar_lista()

    def recargar_lista(self, elegir: int | None = None):
        ok, periodos = seguro(self, nomina.listar_periodos, self.ctx.conn, self.ctx.admin)
        self.selector.blockSignals(True)
        self.selector.clear()
        for p in periodos or []:
            self.selector.addItem(f"{_fmt(p['fecha_inicio'])} al {_fmt(p['fecha_fin'])}  ·  {ESTADO_PERIODO[p['estado']]}", p["id"])
        if elegir is not None:
            self.selector.setCurrentIndex(max(0, self.selector.findData(elegir)))
        self.selector.blockSignals(False)
        self.cargar()

    def cargar(self):
        pid = self.selector.currentData()
        if pid is None:
            self.periodo, self.nominas = None, {}
            poblar(self.tabla, [])
            poblar(self.detalle, [])
            chip(self.chip_estado, "Sin semanas", "chip_neutro")
            self.lb_pasos.setText("Todavía no hay semanas. Pulsa «Abrir semana…» para empezar.")
            self.lb_total.setText("")
            self._botones()
            return
        ok, p = seguro(self, nomina.obtener_periodo, self.ctx.conn, self.ctx.admin, pid)
        if not ok:
            return
        self.periodo = p
        self.nominas = {n["id"]: n for n in p["nominas"]}
        chip(self.chip_estado, ESTADO_PERIODO[p["estado"]], "chip_ok" if p["estado"] != "abierto" else "chip_alerta")
        self.lb_pasos.setText(PASOS[p["estado"]])
        efectivo = sum((Decimal(n["neto"]) for n in p["nominas"] if not n["pagado_en"] and n["neto"] > 0), Decimal(0))
        self.lb_total.setText(f"Total de la semana: {dinero(p['total_neto'])}" + (f"   ·   Por pagar: {dinero(efectivo)}" if efectivo else ""))
        filas = []
        for n in p["nominas"]:
            pago = "Pendiente" if n["neto"] > 0 else "Sin pago (no trabajó)"
            if n["pagado_en"]:
                pago = f"{n['metodo_pago'].capitalize()}" + (" · firmado" if n["recibo_firmado"] else " · sin firma")
            filas.append((n["id"], [n["empleado"], numero(n['dias_trabajados']), dinero(n["total_percepciones"]),
                                    dinero(n["total_deducciones"]), dinero(n["neto"]), pago]))
        poblar(self.tabla, filas, lambda i: QColor(tema.OK) if self.nominas[i]["pagado_en"] else None)
        if filas and self.tabla.currentRow() < 0:
            self.tabla.selectRow(0)
        self._pintar_detalle()
        self._botones()

    def _pintar_detalle(self):
        n = self.nominas.get(id_seleccionado(self.tabla))
        poblar(self.detalle, [(d["id"], [d["concepto"], d["descripcion"] or "",
                                         ("-" if d["tipo"] == "deduccion" else "") + dinero(d["monto"])])
                              for d in (n["detalle"] if n else [])])
        self._botones()

    def _botones(self):
        p, n = self.periodo, self.nominas.get(id_seleccionado(self.tabla))
        estado = p["estado"] if p else None
        self.b_semana.setEnabled(True)
        self.b_calcular.setEnabled(estado == "abierto")
        self.b_aprobar.setEnabled(estado == "abierto" and bool(self.nominas))
        self.b_reabrir.setEnabled(estado == "aprobado" and not any(x["pagado_en"] for x in self.nominas.values()))
        self.b_cerrar.setEnabled(estado == "aprobado" and bool(self.nominas) and all(x["pagado_en"] or x["neto"] <= 0 for x in self.nominas.values()))
        self.b_pagar.setEnabled(estado == "aprobado" and bool(n) and not n["pagado_en"])
        self.b_recibo.setEnabled(bool(n))
        self.b_firmado.setEnabled(bool(n) and bool(n["pagado_en"]) and not n["recibo_firmado"])
        self.b_concepto.setEnabled(estado == "abierto" and bool(n))
        self.b_quitar.setEnabled(estado == "abierto" and bool(n))

    # ------------------------------------------------------------ acciones
    def abrir_semana(self):
        hoy = date.today()
        lunes_actual = hoy - timedelta(days=hoy.weekday())
        opciones = {f"Esta semana ({_fmt(lunes_actual)} al {_fmt(lunes_actual + timedelta(days=6))})": hoy,
                    f"Semana pasada ({_fmt(lunes_actual - timedelta(days=7))} al {_fmt(lunes_actual - timedelta(days=1))})":
                        hoy - timedelta(days=7)}
        from PySide6.QtWidgets import QInputDialog
        texto, ok = QInputDialog.getItem(self, "Abrir semana", "¿Qué semana quieres pagar?", list(opciones), 1, False)
        if not ok:
            return
        # al abrir la primera semana se da de alta el sueldo mínimo a quien no tenga sueldo
        okm, altas = seguro(self, nomina.aplicar_salario_minimo, self.ctx.conn, self.ctx.admin)
        ok2, pid = seguro(self, nomina.crear_periodo_semanal, self.ctx.conn, self.ctx.admin, opciones[texto])
        if ok2:
            self.recargar_lista(pid)

    def calcular(self):
        if not self.periodo:
            return
        ok, r = seguro(self, nomina.calcular_periodo, self.ctx.conn, self.ctx.admin, self.periodo["id"])
        if not ok:
            return
        self.cargar()
        if r["advertencias"]:
            QMessageBox.information(self, "Revisa antes de aprobar",
                                    "Estos avisos no detienen el cálculo, pero conviene revisarlos:\n\n• " + "\n• ".join(r["advertencias"]))

    def aprobar(self):
        if self.periodo and QMessageBox.question(
                self, "Aprobar semana", "Al aprobar ya no se podrán cambiar los montos (puedes reabrir mientras no pagues a nadie).\n\n¿Aprobar?") == QMessageBox.Yes:
            if seguro(self, nomina.aprobar_periodo, self.ctx.conn, self.ctx.admin, self.periodo["id"])[0]:
                self.recargar_lista(self.periodo["id"])

    def reabrir(self):
        if self.periodo and seguro(self, nomina.reabrir_periodo, self.ctx.conn, self.ctx.admin, self.periodo["id"])[0]:
            self.recargar_lista(self.periodo["id"])

    def cerrar(self):
        if self.periodo and QMessageBox.question(self, "Cerrar semana", "¿Cerrar la semana? Ya no se podrá modificar.") == QMessageBox.Yes:
            if seguro(self, nomina.cerrar_periodo, self.ctx.conn, self.ctx.admin, self.periodo["id"])[0]:
                self.recargar_lista(self.periodo["id"])

    def pagar(self):
        n = self.nominas.get(id_seleccionado(self.tabla))
        if not n:
            return
        dlg = PagoDialog(self, n["empleado"], n["neto"])
        if dlg.exec() and seguro(self, nomina.registrar_pago_empleado, self.ctx.conn, self.ctx.admin, n["id"],
                                 dlg.metodo == "efectivo", dlg.metodo, dlg.firmado.isChecked())[0]:
            self.cargar()
            if not dlg.firmado.isChecked():
                QMessageBox.information(self, "Recibo", "Pago registrado. Imprime el recibo y pídele que lo firme; "
                                        "luego usa «Marcar recibo firmado».")

    def recibo(self):
        n = self.nominas.get(id_seleccionado(self.tabla))
        if not n:
            return
        ruta = RAIZ / "recibos" / f"recibo_{n['empleado'].replace(' ', '_')}_{self.periodo['fecha_inicio']}.pdf"
        ok, destino = seguro(self, tickets.recibo_nomina_pdf, self.ctx.conn, self.ctx.admin, n["id"], ruta)
        if ok:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(destino)))

    def firmado(self):
        n = self.nominas.get(id_seleccionado(self.tabla))
        if n and seguro(self, nomina.marcar_recibo_firmado, self.ctx.conn, self.ctx.admin, n["id"])[0]:
            self.cargar()

    def agregar_concepto(self):
        n = self.nominas.get(id_seleccionado(self.tabla))
        if not n:
            return
        dlg = ConceptoDialog(self)
        if dlg.exec() and seguro(self, nomina.agregar_concepto, self.ctx.conn, self.ctx.admin, n["id"],
                                 dlg.tipo.currentData(), a_decimal(dlg.monto.text()), dlg.descripcion.text())[0]:
            self.cargar()

    def quitar_concepto(self):
        did = id_seleccionado(self.detalle)
        if did is None:
            QMessageBox.information(self, "Oceánica", "Selecciona el concepto que quieres quitar (solo los capturados a mano).")
            return
        if seguro(self, nomina.quitar_concepto, self.ctx.conn, self.ctx.admin, did)[0]:
            self.cargar()
