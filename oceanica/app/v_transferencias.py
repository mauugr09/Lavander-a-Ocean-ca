"""Transferencias por confirmar contra el banco (administrador)."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ..servicios import caja
from .util import crear_tabla, dinero, etiqueta, fecha_hora, id_seleccionado, poblar, seguro


class TransferenciasView(QWidget):
    titulo = "Transferencias"

    def __init__(self, ctx):
        super().__init__()
        self.setObjectName("pagina")
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.addWidget(etiqueta("Transferencias por confirmar", "titulo"))
        lay.addWidget(etiqueta("Revisa en el banco que el dinero llegó. Si no llegó, recházala y la orden recupera su saldo "
                               "(requiere caja abierta).", "suave", True))
        self.tabla = crear_tabla(["Folio", "Fecha", "Monto", "Clave de rastreo", "Cobró", "Orden"], derecha=(2,), estirar=3)
        lay.addWidget(self.tabla, 1)
        fila = QHBoxLayout()
        self.b_ok = QPushButton("Confirmar: ya llegó")
        self.b_ok.setProperty("rol", "primario")
        self.b_no = QPushButton("Rechazar: no llegó")
        self.b_no.setProperty("rol", "peligro")
        fila.addWidget(self.b_ok)
        fila.addWidget(self.b_no)
        fila.addStretch(1)
        lay.addLayout(fila)
        self.b_ok.clicked.connect(self.confirmar)
        self.b_no.clicked.connect(self.rechazar)

    def al_mostrar(self):
        ok, filas = seguro(self, caja.listar_transferencias_pendientes, self.ctx.conn, self.ctx.admin)
        poblar(self.tabla, [(f["id"], [f["folio"], fecha_hora(f["pagado_en"]), dinero(f["monto"]), f["referencia"] or "",
                                       f["cobro"], f["estado_orden"]]) for f in filas or []])

    def confirmar(self):
        pid = id_seleccionado(self.tabla)
        if pid is not None and seguro(self, caja.confirmar_transferencia, self.ctx.conn, self.ctx.admin, pid)[0]:
            self.al_mostrar()

    def rechazar(self):
        pid = id_seleccionado(self.tabla)
        if pid is None:
            return
        motivo, ok = QInputDialog.getText(self, "Rechazar transferencia", "Motivo (por ejemplo: no aparece en el banco):")
        if ok and motivo.strip() and seguro(self, caja.rechazar_transferencia, self.ctx.conn, self.ctx.admin, pid, motivo)[0]:
            self.al_mostrar()
