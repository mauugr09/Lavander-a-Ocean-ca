"""Configuración del negocio y respaldos (administrador)."""
from __future__ import annotations

from PySide6.QtWidgets import (QHBoxLayout, QInputDialog, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from .. import respaldos
from ..servicios import configuracion
from .util import crear_tabla, etiqueta, id_seleccionado, poblar, seguro

OPCIONES = {"entrega_requiere_pago_total": ("si", "no"), "asistencia_paga_justificada": ("si", "no"),
            "entrega_transferencia_pendiente": ("no", "admin", "todos"), "ticket_logo": ("si", "no")}
MULTILINEA = {"ticket_condiciones": "Una condición por renglón.", "ticket_almacenaje": ""}


def _resumen(valor: str) -> str:
    v = " · ".join(l.strip() for l in (valor or "").splitlines() if l.strip())
    return v if len(v) <= 70 else v[:69] + "…"


class ConfigView(QWidget):
    titulo = "Configuración"

    def __init__(self, ctx):
        super().__init__()
        self.setObjectName("pagina")
        self.ctx = ctx
        self.filas: dict[str, dict] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.addWidget(etiqueta("Configuración", "titulo"))
        lay.addWidget(etiqueta("Seleccione un ajuste y pulse «Cambiar valor» (o haga doble clic). "
                               "Aquí se fija, por ejemplo, el cargo por servicio a domicilio.", "suave", True))
        fila = QHBoxLayout()
        self.b_editar = QPushButton("Cambiar valor")
        self.b_editar.setProperty("rol", "primario")
        self.b_respaldo = QPushButton("Hacer respaldo ahora")
        fila.addWidget(self.b_editar)
        fila.addStretch(1)
        fila.addWidget(self.b_respaldo)
        lay.addLayout(fila)
        self.lb_respaldo = etiqueta("", "suave", True)
        lay.addWidget(self.lb_respaldo)
        self.tabla = crear_tabla(["Ajuste", "Valor"], estirar=0)
        lay.addWidget(self.tabla, 1)
        self.b_editar.clicked.connect(self.editar)
        self.tabla.itemActivated.connect(lambda *_: self.editar())
        self.b_respaldo.clicked.connect(self.respaldar)

    def al_mostrar(self):
        e = respaldos.estado(self.ctx.conn)
        self.lb_respaldo.setText(e["mensaje"] + ("" if e["nivel"] == "ok" else
                                 ".  Conecte el disco externo y pulse «Hacer respaldo ahora»."))
        self.lb_respaldo.setProperty("rol", "suave" if e["nivel"] == "ok" else "error")
        self.lb_respaldo.style().unpolish(self.lb_respaldo)
        self.lb_respaldo.style().polish(self.lb_respaldo)
        ok, filas = seguro(self, configuracion.listar, self.ctx.conn)
        self.filas = {f["clave"]: f for f in filas or []}
        poblar(self.tabla, [(f["clave"], [f["descripcion"] or f["clave"], _resumen(f["valor"])]) for f in self.filas.values()])

    def editar(self):
        clave = id_seleccionado(self.tabla)
        if clave is None:
            return
        f = self.filas[clave]
        if clave in OPCIONES:
            ops = list(OPCIONES[clave])
            valor, ok = QInputDialog.getItem(self, "Cambiar ajuste", f["descripcion"] or clave, ops, max(0, ops.index(f["valor"]) if f["valor"] in ops else 0), False)
        elif clave in MULTILINEA:
            valor, ok = QInputDialog.getMultiLineText(self, "Cambiar ajuste",
                                                      f"{f['descripcion'] or clave}\n{MULTILINEA[clave]}".strip(),
                                                      f["valor"])
        else:
            valor, ok = QInputDialog.getText(self, "Cambiar ajuste", f["descripcion"] or clave, text=f["valor"])
        if ok and seguro(self, configuracion.establecer, self.ctx.conn, self.ctx.admin, clave, valor)[0]:
            self.al_mostrar()

    def respaldar(self):
        try:
            ruta = respaldos.crear_respaldo("manual", self.ctx.admin["id"])
        except Exception as e:  # mysqldump ausente, disco lleno, etc.
            QMessageBox.critical(self, "Respaldo", f"No se pudo crear el respaldo:\n{e}")
            return
        QMessageBox.information(self, "Respaldo", f"Respaldo creado:\n{ruta}")
        self.al_mostrar()
