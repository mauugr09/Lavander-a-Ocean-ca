"""Ventana de cobro por pasos, una pregunta a la vez y con botones grandes.

1. ¿Cómo va a pagar?   Todo ahora · Un anticipo · Al recoger
2. ¿Con qué paga?      Efectivo · Transferencia
3. Efectivo: ¿con cuánto paga? (billetes sugeridos y teclado) y el cambio en grande.
   Transferencia: confirmar que mostró la captura (y la clave de rastreo, si la tiene).

Resultado en self.pago = {'metodo_pago_id', 'monto', 'referencia'} o None si no se cobra nada ahora.
"""
from __future__ import annotations

import math
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QGridLayout, QHBoxLayout, QLineEdit, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..servicios import caja
from .botones import COLORES, BotonGrande, Teclado
from .iconos import poner
from .tema import OK
from .util import dinero, etiqueta

P_MODO, P_PARTE, P_METODO, P_EFECTIVO, P_TRANSFERENCIA = range(5)


def sugerencias_billetes(monto: Decimal, cuantas: int = 4) -> list[Decimal]:
    """Cantidades con las que suele pagar la gente: 126 → 150, 200, 500, 1000."""
    vistos: list[Decimal] = []
    for b in (50, 100, 200, 500, 1000):
        v = Decimal(math.ceil(monto / b) * b)
        if v > monto and v not in vistos:
            vistos.append(v)
    return sorted(vistos)[:cuantas]


def _pagina(titulo: str) -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(12)
    lb = etiqueta(titulo, "pregunta")
    lb.setStyleSheet("font-size: 15pt; font-weight: 700;")
    lay.addWidget(lb)
    return w, lay


def _boton_accion(texto: str, ico: str = "check") -> QPushButton:
    b = poner(QPushButton(texto), ico, "white", 24)
    b.setProperty("rol", "primario")
    b.setMinimumHeight(58)
    b.setStyleSheet("font-size: 15pt;")
    return b


class CobroDialog(QDialog):
    def __init__(self, ctx, parent, importe: Decimal, titulo: str, permite_cero: bool, texto_importe: str = "Total",
                 reembolso: bool = False):
        super().__init__(parent)
        self.pago = None
        self.importe = Decimal(importe)
        self.permite_cero, self.reembolso = permite_cero, reembolso
        self.monto = self.importe
        self.metodo: dict | None = None
        self.historial: list[int] = []
        self.metodos = {m["id"]: m for m in caja.listar_metodos(ctx.conn)}
        self.setWindowTitle(titulo)
        self.setModal(True)
        self.setMinimumWidth(640)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(12)
        lay.addWidget(etiqueta(titulo, "subtitulo"))
        self.lb_importe = etiqueta(f"{texto_importe}: {dinero(self.importe)}", "titulo")
        self.lb_importe.setStyleSheet("font-size: 22pt;")
        lay.addWidget(self.lb_importe)

        self.pila = QStackedWidget()
        lay.addWidget(self.pila, 1)
        self._pag_modo()
        self._pag_parte()
        self._pag_metodo()
        self._pag_efectivo()
        self._pag_transferencia()

        self.msg = etiqueta("", "error", True)
        self.msg.setStyleSheet("font-size: 12pt;")
        lay.addWidget(self.msg)
        pie = QHBoxLayout()
        self.b_atras = poner(QPushButton("Atrás"), "arrow-left")
        self.b_atras.setMinimumHeight(48)
        self.b_cancelar = QPushButton("Cancelar")
        self.b_cancelar.setMinimumHeight(48)
        pie.addWidget(self.b_atras)
        pie.addStretch(1)
        pie.addWidget(self.b_cancelar)
        lay.addLayout(pie)
        self.b_atras.clicked.connect(self.atras)
        self.b_cancelar.clicked.connect(self.reject)

        # Un reembolso siempre es por el total pagado: se empieza en «¿con qué?».
        self._ir(P_METODO if reembolso else P_MODO, guardar=False)

    # ---------------------------------------------------------------- páginas
    def _pag_modo(self):
        w, lay = _pagina("¿Cómo va a pagar el cliente?")
        self.b_todo = BotonGrande("circle-check", "Paga todo ahora", dinero(self.importe), COLORES[3], alto=96)
        self.b_parte = BotonGrande("receipt", "Deja un anticipo" if self.permite_cero else "Paga solo una parte",
                                   "El resto se cobra después", COLORES[0], alto=96)
        self.b_despues = BotonGrande("clock", "Paga al recoger", "No se cobra nada ahora", COLORES[4], alto=96)
        self.b_despues.setVisible(self.permite_cero)
        for b in (self.b_todo, self.b_parte, self.b_despues):
            lay.addWidget(b)
        lay.addStretch(1)
        self.b_todo.clicked.connect(lambda: self.elegir_modo("todo"))
        self.b_parte.clicked.connect(lambda: self.elegir_modo("parte"))
        self.b_despues.clicked.connect(lambda: self.elegir_modo("despues"))
        self.pila.addWidget(w)

    def _pag_parte(self):
        w, lay = _pagina("¿Cuánto deja ahora?")
        self.teclado_parte = Teclado(prefijo="$")
        lay.addWidget(self.teclado_parte)
        self.lb_resto = etiqueta("", "suave")
        self.lb_resto.setStyleSheet("font-size: 13pt;")
        self.lb_resto.setAlignment(Qt.AlignRight)
        lay.addWidget(self.lb_resto)
        self.b_parte_ok = _boton_accion("Continuar", "arrow-right")
        lay.addWidget(self.b_parte_ok)
        self.teclado_parte.pantalla.textChanged.connect(self._ver_resto)
        self.teclado_parte.pantalla.returnPressed.connect(self.confirmar_parte)
        self.b_parte_ok.clicked.connect(self.confirmar_parte)
        self.pila.addWidget(w)

    def _pag_metodo(self):
        w, lay = _pagina("¿Cómo se devuelve el dinero?" if self.reembolso else "¿Con qué paga?")
        self.lb_a_cobrar = etiqueta("", "suave")
        self.lb_a_cobrar.setStyleSheet("font-size: 13pt;")
        lay.addWidget(self.lb_a_cobrar)
        fila = QHBoxLayout()
        fila.setSpacing(12)
        self.botones_metodo: dict[int, BotonGrande] = {}
        for i, m in enumerate(self.metodos.values()):
            icono = "cash-banknote" if m["es_efectivo"] else ("device-mobile" if m["requiere_confirmacion"] else "credit-card")
            b = BotonGrande(icono, m["nombre"], "", COLORES[(3, 1, 2)[i % 3]], alto=130)
            b.clicked.connect(lambda _=False, mid=m["id"]: self.elegir_metodo(mid))
            self.botones_metodo[m["id"]] = b
            fila.addWidget(b)
        lay.addLayout(fila)
        lay.addStretch(1)
        self.pila.addWidget(w)

    def _pag_efectivo(self):
        w, lay = _pagina("¿Con cuánto paga el cliente?")
        self.rej_billetes = QGridLayout()
        self.rej_billetes.setSpacing(8)
        lay.addLayout(self.rej_billetes)
        self.teclado_recibido = Teclado(prefijo="$", alto_tecla=52)
        self.recibido = self.teclado_recibido.pantalla
        lay.addWidget(self.teclado_recibido)
        self.lb_cambio = etiqueta("")
        self.lb_cambio.setAlignment(Qt.AlignRight)
        self.lb_cambio.setStyleSheet(f"font-size: 24pt; font-weight: 700; color: {OK};")
        lay.addWidget(self.lb_cambio)
        self.b_cobrar_ef = _boton_accion("")
        lay.addWidget(self.b_cobrar_ef)
        self.recibido.textChanged.connect(self._ver_cambio)
        self.recibido.returnPressed.connect(self._aceptar)
        self.b_cobrar_ef.clicked.connect(self._aceptar)
        self.pila.addWidget(w)

    def _pag_transferencia(self):
        w, lay = _pagina("Pida al cliente el comprobante de la transferencia")
        self.captura = QCheckBox("  Ya vi la captura del comprobante")
        self.captura.setStyleSheet("QCheckBox { font-size: 13pt; padding: 10px; } "
                                   "QCheckBox::indicator { width: 30px; height: 30px; }")
        lay.addWidget(self.captura)
        lay.addWidget(etiqueta("Clave de rastreo (si el cliente la tiene):", "suave"))
        self.referencia = QLineEdit()
        self.referencia.setPlaceholderText("Opcional")
        self.referencia.setMinimumHeight(44)
        self.referencia.setStyleSheet("font-size: 13pt;")
        lay.addWidget(self.referencia)
        lay.addWidget(etiqueta("La encargada confirmará después en el banco que el dinero llegó.", "suave", True))
        lay.addStretch(1)
        self.b_cobrar_tr = _boton_accion("")
        lay.addWidget(self.b_cobrar_tr)
        self.referencia.returnPressed.connect(self._aceptar)
        self.b_cobrar_tr.clicked.connect(self._aceptar)
        self.pila.addWidget(w)

    # ------------------------------------------------------------ navegación
    def _ir(self, pagina: int, guardar: bool = True):
        if guardar:
            self.historial.append(self.pila.currentIndex())
        self.pila.setCurrentIndex(pagina)
        self.msg.setText("")
        self.b_atras.setVisible(bool(self.historial))
        if pagina == P_PARTE:
            self.teclado_parte.pantalla.setFocus()
        elif pagina == P_METODO:
            verbo = "Se devuelve" if self.reembolso else "Se cobra"
            self.lb_a_cobrar.setText(f"{verbo}: {dinero(self.monto)}")
        elif pagina == P_EFECTIVO:
            self._armar_billetes()
            self.recibido.clear()
            self.b_cobrar_ef.setText(f"{'Devolver' if self.reembolso else 'Cobrar'} {dinero(self.monto)}")
            self._ver_cambio()
            self.recibido.setFocus()
        elif pagina == P_TRANSFERENCIA:
            self.b_cobrar_tr.setText(f"Registrar {'devolución' if self.reembolso else 'pago'} de {dinero(self.monto)}")

    def atras(self):
        if self.historial:
            self.pila.setCurrentIndex(self.historial.pop())
            self.msg.setText("")
            self.b_atras.setVisible(bool(self.historial))

    def elegir_modo(self, modo: str):
        if modo == "despues":
            self.pago = None
            self.accept()
        elif modo == "todo":
            self.monto = self.importe
            self._ir(P_METODO)
        else:
            self.teclado_parte.pantalla.clear()
            self._ver_resto()
            self._ir(P_PARTE)

    def _ver_resto(self):
        v = self.teclado_parte.valor()
        if v is not None and 0 < v < self.importe:
            self.lb_resto.setText(f"Quedará pendiente: {dinero(self.importe - v)}")
        else:
            self.lb_resto.setText("")
        self.msg.setText("")

    def confirmar_parte(self):
        v = self.teclado_parte.valor()
        if v is None or v <= 0:
            self.msg.setText("Escriba cuánto deja el cliente.")
            return
        if v > self.importe:
            self.msg.setText(f"No puede ser más de {dinero(self.importe)}.")
            return
        self.monto = v.quantize(Decimal("0.01"))
        self._ir(P_METODO)

    def elegir_metodo(self, metodo_id: int):
        self.metodo = self.metodos[metodo_id]
        if self.metodo["requiere_confirmacion"]:
            self.captura.setChecked(False)
            self.referencia.clear()
            self._ir(P_TRANSFERENCIA)
        elif self.metodo["es_efectivo"] and not self.reembolso:
            self._ir(P_EFECTIVO)
        else:
            self._aceptar()

    def _armar_billetes(self):
        while self.rej_billetes.count():
            self.rej_billetes.takeAt(0).widget().deleteLater()
        opciones = [("Exacto", self.monto)] + [(f"${v:,.0f}", v) for v in sugerencias_billetes(self.monto)]
        for i, (texto, v) in enumerate(opciones):
            b = QPushButton(texto)
            b.setMinimumHeight(52)
            b.setStyleSheet("font-size: 14pt; font-weight: 600;")
            b.clicked.connect(lambda _=False, v=v: self.recibido.setText(format(v, "f")))
            self.rej_billetes.addWidget(b, 0, i)

    def _ver_cambio(self):
        r = self.teclado_recibido.valor()
        if r is None:
            self.lb_cambio.setText("Cambio: —")
        elif r < self.monto:
            self.lb_cambio.setText(f"Faltan {dinero(self.monto - r)}")
        else:
            self.lb_cambio.setText(f"Cambio: {dinero(r - self.monto)}")
        self.msg.setText("")

    # ----------------------------------------------------------------- final
    def _aceptar(self):
        if self.metodo is None:
            return
        m = self.metodo
        ref = None
        if self.pila.currentIndex() == P_EFECTIVO:
            r = self.teclado_recibido.valor()
            if r is not None and r < self.monto:
                self.msg.setText("Lo que entregó el cliente es menos de lo que se cobra.")
                return
        if m["requiere_confirmacion"]:
            ref = self.referencia.text().strip()
            if not ref and not self.captura.isChecked():
                self.msg.setText("Pida la captura de pantalla del comprobante y marque la casilla "
                                 "(o anote la clave de rastreo).")
                return
            ref = ref or "CAPTURA DE PANTALLA"  # la encargada confirma después en el banco
        self.pago = {"metodo_pago_id": m["id"], "monto": self.monto, "referencia": ref or None}
        self.accept()
