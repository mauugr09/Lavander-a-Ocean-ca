"""Clientes: búsqueda, alta, edición e historial."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ..servicios import clientes
from .dialogos import ClienteDialog
from .util import ESTADOS, crear_tabla, dinero, etiqueta, fecha_hora, id_seleccionado, poblar, seguro


class ClientesView(QWidget):
    titulo = "Clientes"

    def __init__(self, ctx):
        super().__init__()
        self.setObjectName("pagina")
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        fila = QHBoxLayout()
        self.buscar = QLineEdit()
        self.buscar.setPlaceholderText("Buscar por nombre o teléfono")
        self.b_nuevo = QPushButton("Nuevo cliente")
        self.b_nuevo.setProperty("rol", "primario")
        self.b_editar = QPushButton("Editar")
        fila.addWidget(self.buscar, 1)
        fila.addWidget(self.b_nuevo)
        fila.addWidget(self.b_editar)
        lay.addLayout(fila)
        self.tabla = crear_tabla(["Nombre", "Teléfono", "Correo", "Notas"])
        lay.addWidget(self.tabla, 3)
        lay.addWidget(etiqueta("Órdenes del cliente", "subtitulo"))
        self.hist = crear_tabla(["Folio", "Fecha", "Estado", "Total"], derecha=(3,), estirar=1)
        lay.addWidget(self.hist, 2)
        self.datos: dict[int, dict] = {}
        self.buscar.textChanged.connect(self.recargar)
        self.tabla.itemSelectionChanged.connect(self._historial)
        self.tabla.itemActivated.connect(lambda *_: self.editar())
        self.b_nuevo.clicked.connect(self.nuevo)
        self.b_editar.clicked.connect(self.editar)

    def al_mostrar(self):
        self.recargar()
        self.buscar.setFocus()

    def recargar(self):
        ok, filas = seguro(self, clientes.buscar_clientes, self.ctx.conn, self.buscar.text(), True, 200)
        filas = filas or []
        self.datos = {c["id"]: c for c in filas}
        poblar(self.tabla, [(c["id"], [" ".join(filter(None, [c["nombre"], c["apellidos"]])), c["telefono"] or "",
                                       c["email"] or "", c["notas"] or ""]) for c in filas])
        self._historial()

    def _historial(self):
        cid = id_seleccionado(self.tabla)
        if cid is None:
            return poblar(self.hist, [])
        ok, h = seguro(self, clientes.historial_ordenes, self.ctx.conn, cid)
        poblar(self.hist, [(o["orden_id"], [o["folio"], fecha_hora(o["fecha_recepcion"]), ESTADOS[o["estado"]], dinero(o["total"])])
                           for o in h or []])

    def nuevo(self):
        dlg = ClienteDialog(self)
        if dlg.exec():
            sesion = self.ctx.identificar(self, sensible=False)
            if sesion:
                ok, _ = seguro(self, clientes.crear_cliente, self.ctx.conn, sesion, **dlg.valores())
                if ok:
                    self.recargar()

    def editar(self):
        cid = id_seleccionado(self.tabla)
        if cid is None:
            return
        dlg = ClienteDialog(self, self.datos.get(cid))
        if dlg.exec():
            sesion = self.ctx.identificar(self, sensible=False)
            if sesion:
                ok, _ = seguro(self, clientes.actualizar_cliente, self.ctx.conn, sesion, cid, **dlg.valores())
                if ok:
                    self.recargar()
