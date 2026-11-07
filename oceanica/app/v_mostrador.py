"""Nueva orden: captura rápida por teclado."""
from __future__ import annotations

import unicodedata
from datetime import datetime, timedelta
from decimal import Decimal

from PySide6.QtCore import QEvent, QStringListModel, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QCompleter, QDateTimeEdit, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from ..servicios import caja, catalogo, clientes, configuracion, ordenes, tickets
from .carrito import Carrito
from .dialogos import ClienteDialog, CobroDialog, TicketDialog
from .util import a_decimal, cantidad_txt, crear_tabla, dinero, etiqueta, poblar, seguro, tarjeta, UNIDADES


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


class _Filtro(QLineEdit):
    """Campo de búsqueda: la flecha abajo pasa a la lista."""

    def __init__(self, *a, destino=None):
        super().__init__(*a)
        self.destino = destino

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Down and self.destino is not None:
            self.destino.setFocus()
            return
        super().keyPressEvent(e)


class MostradorView(QWidget):
    titulo = "Nueva orden"

    def __init__(self, ctx, ir_a_orden=None):
        super().__init__()
        self.setObjectName("pagina")
        self.ctx, self.ir_a_orden = ctx, ir_a_orden
        self.carrito = Carrito()
        self.servicios: list[dict] = []
        self.visibles: list[dict] = []
        self.cliente_id: int | None = None
        self.mapa_clientes: dict[str, int] = {}

        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(16, 16, 16, 16)
        raiz.setSpacing(14)

        # ---- izquierda: cliente y servicios
        izq = QVBoxLayout()
        izq.setSpacing(8)
        izq.addWidget(etiqueta("Cliente  (F3)", "subtitulo"))
        fila_cli = QHBoxLayout()
        self.cliente = QLineEdit()
        self.cliente.setPlaceholderText("Nombre o teléfono — déjalo vacío para venta de mostrador")
        self.modelo_cli = QStringListModel()
        self.completer = QCompleter(self.modelo_cli, self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.cliente.setCompleter(self.completer)
        self.b_nuevo_cli = QPushButton("Nuevo (F4)")
        self.b_quitar_cli = QPushButton("✕")
        self.b_quitar_cli.setToolTip("Quitar cliente")
        self.b_quitar_cli.setFixedWidth(40)
        fila_cli.addWidget(self.cliente, 1)
        fila_cli.addWidget(self.b_nuevo_cli)
        fila_cli.addWidget(self.b_quitar_cli)
        izq.addLayout(fila_cli)
        self.info_cli = etiqueta("", "suave")
        izq.addWidget(self.info_cli)

        izq.addSpacing(6)
        izq.addWidget(etiqueta("Servicio  (F2)", "subtitulo"))
        self.tabla_serv = crear_tabla(["Servicio", "Unidad", "Precio"], derecha=(2,))
        self.filtro = _Filtro(destino=self.tabla_serv)
        self.filtro.setPlaceholderText("Escribe para buscar…  ↓ para elegir de la lista · Enter para dar la cantidad")
        izq.addWidget(self.filtro)
        izq.addWidget(self.tabla_serv, 1)
        fila_cant = QHBoxLayout()
        self.lb_cant = QLabel("Cantidad")
        self.cantidad = QLineEdit()
        self.cantidad.setPlaceholderText("0")
        self.cantidad.setMaximumWidth(120)
        self.lb_unidad = etiqueta("", "suave")
        self.b_agregar = QPushButton("Agregar (Enter)")
        fila_cant.addWidget(self.lb_cant)
        fila_cant.addWidget(self.cantidad)
        fila_cant.addWidget(self.lb_unidad)
        fila_cant.addStretch(1)
        fila_cant.addWidget(self.b_agregar)
        izq.addLayout(fila_cant)
        raiz.addLayout(izq, 5)

        # ---- derecha: la orden
        der = tarjeta()
        dl = QVBoxLayout(der)
        dl.setContentsMargins(14, 14, 14, 14)
        dl.addWidget(etiqueta("Orden", "subtitulo"))
        self.tabla_carrito = crear_tabla(["Servicio", "Cantidad", "Precio", "Importe"], derecha=(1, 2, 3))
        dl.addWidget(self.tabla_carrito, 1)
        fila_q = QHBoxLayout()
        self.b_quitar = QPushButton("Quitar línea (Supr)")
        fila_q.addWidget(self.b_quitar)
        fila_q.addStretch(1)
        dl.addLayout(fila_q)
        self.lb_subtotal = etiqueta("", "suave")
        dl.addWidget(self.lb_subtotal)
        self.descuento = QLineEdit()
        self.descuento.setPlaceholderText("Descuento $")
        self.descuento.setVisible(ctx.es_admin)
        dl.addWidget(self.descuento)
        self.lb_total = etiqueta("$0.00", "total")
        self.lb_total.setAlignment(Qt.AlignRight)
        dl.addWidget(self.lb_total)
        fila_f = QHBoxLayout()
        fila_f.addWidget(QLabel("Entrega"))
        self.entrega = QDateTimeEdit()
        self.entrega.setCalendarPopup(True)
        self.entrega.setDisplayFormat("dd/MM/yyyy HH:mm")
        fila_f.addWidget(self.entrega, 1)
        dl.addLayout(fila_f)
        self.obs = QLineEdit()
        self.obs.setPlaceholderText("Observaciones (opcional)")
        dl.addWidget(self.obs)
        fila_b = QHBoxLayout()
        self.b_limpiar = QPushButton("Limpiar (Esc)")
        self.b_guardar = QPushButton("Guardar y cobrar (F5)")
        self.b_guardar.setProperty("rol", "primario")
        self.b_guardar.setMinimumHeight(40)
        fila_b.addWidget(self.b_limpiar)
        fila_b.addWidget(self.b_guardar, 1)
        dl.addLayout(fila_b)
        raiz.addWidget(der, 4)

        # ---- señales y atajos
        self.filtro.textChanged.connect(self._filtrar)
        self.filtro.returnPressed.connect(self._ir_a_cantidad)
        self.tabla_serv.itemActivated.connect(lambda *_: self._ir_a_cantidad())
        self.tabla_serv.itemSelectionChanged.connect(self._mostrar_unidad)
        self.cantidad.returnPressed.connect(self._agregar)
        self.b_agregar.clicked.connect(self._agregar)
        self.b_quitar.clicked.connect(self._quitar)
        self.b_limpiar.clicked.connect(self.limpiar)
        self.b_guardar.clicked.connect(self.guardar)
        self.b_nuevo_cli.clicked.connect(self.nuevo_cliente)
        self.b_quitar_cli.clicked.connect(self._quitar_cliente)
        self.cliente.textEdited.connect(self._buscar_clientes)
        self.completer.activated[str].connect(self._elegir_cliente)
        self.descuento.textChanged.connect(self._refrescar_totales)
        for tecla, accion in (("F2", self.filtro.setFocus), ("F3", self.cliente.setFocus), ("F4", self.nuevo_cliente),
                              ("F5", self.guardar), ("Esc", self.limpiar)):
            QShortcut(QKeySequence(tecla), self, activated=accion)
        QShortcut(QKeySequence(Qt.Key_Delete), self.tabla_carrito, activated=self._quitar,
                  context=Qt.WidgetWithChildrenShortcut)

    # ---------------------------------------------------------------- datos
    def al_mostrar(self):
        ok, servicios = seguro(self, catalogo.listar_servicios, self.ctx.conn)
        self.servicios = servicios or []
        self._filtrar()
        self._fecha_por_defecto()
        self.descuento.setVisible(self.ctx.es_admin)
        self.filtro.setFocus()

    def _fecha_por_defecto(self):
        try:
            dias = int(configuracion.obtener(self.ctx.conn, "dias_entrega_default", "2") or 2)
        except (ValueError, Exception):
            dias = 2
        d = datetime.now().replace(second=0, microsecond=0) + timedelta(days=dias)
        self.entrega.setDateTime(d)

    def _filtrar(self):
        q = _norm(self.filtro.text())
        self.visibles = [s for s in self.servicios if q in _norm(s["nombre"])]
        poblar(self.tabla_serv, [(s["id"], [s["nombre"], UNIDADES[s["unidad"]], dinero(s["precio"])]) for s in self.visibles])
        if self.visibles:
            self.tabla_serv.selectRow(0)
        self._mostrar_unidad()

    def _servicio_actual(self) -> dict | None:
        r = self.tabla_serv.currentRow()
        return self.visibles[r] if 0 <= r < len(self.visibles) else None

    def _mostrar_unidad(self):
        s = self._servicio_actual()
        self.lb_unidad.setText(("kilos" if s["unidad"] == "kilo" else "piezas") if s else "")

    def _ir_a_cantidad(self):
        if self._servicio_actual():
            self.cantidad.setFocus()
            self.cantidad.selectAll()

    def _agregar(self):
        s = self._servicio_actual()
        if not s:
            QMessageBox.information(self, "Oceánica", "Elige un servicio de la lista.")
            return
        ok, _ = seguro(self, self.carrito.agregar, s, a_decimal(self.cantidad.text()))
        if not ok:
            self.cantidad.setFocus()
            return
        self.cantidad.clear()
        self.filtro.clear()
        self._refrescar_carrito()
        self.filtro.setFocus()

    def _quitar(self):
        r = self.tabla_carrito.currentRow()
        if r >= 0:
            self.carrito.quitar(r)
            self._refrescar_carrito()

    def _refrescar_carrito(self):
        filas = [(i, [l.nombre, cantidad_txt(l.cantidad, l.unidad), dinero(l.precio), dinero(l.importe)])
                 for i, l in enumerate(self.carrito.lineas)]
        poblar(self.tabla_carrito, filas)
        self._refrescar_totales()

    def _refrescar_totales(self):
        d = a_decimal(self.descuento.text()) if self.ctx.es_admin else None
        self.carrito.descuento = d if d is not None and d >= 0 else Decimal("0.00")
        self.lb_subtotal.setText(f"Subtotal: {dinero(self.carrito.subtotal)}" if self.carrito.descuento else "")
        self.lb_total.setText(dinero(self.carrito.total))

    # -------------------------------------------------------------- cliente
    def _buscar_clientes(self, texto: str):
        self.cliente_id = None
        self.info_cli.setText("")
        if len(texto.strip()) < 2:
            self.modelo_cli.setStringList([])
            return
        ok, filas = seguro(self, clientes.buscar_clientes, self.ctx.conn, texto, True, 10)
        self.mapa_clientes = {}
        for c in filas or []:
            nombre = " ".join(filter(None, [c["nombre"], c["apellidos"]]))
            etiq = f"{nombre} · {c['telefono']}" if c["telefono"] else nombre
            while etiq in self.mapa_clientes:
                etiq += " "
            self.mapa_clientes[etiq] = c["id"]
        self.modelo_cli.setStringList(list(self.mapa_clientes))

    def _elegir_cliente(self, etiqueta_: str):
        self.cliente_id = self.mapa_clientes.get(etiqueta_)
        if self.cliente_id:
            self.info_cli.setText("✔ Cliente seleccionado")
            self.filtro.setFocus()

    def _quitar_cliente(self):
        self.cliente.clear()
        self.cliente_id = None
        self.info_cli.setText("")

    def nuevo_cliente(self):
        dlg = ClienteDialog(self)
        if not dlg.exec():
            return
        sesion = self.ctx.identificar(self, sensible=False)
        if not sesion:
            return
        ok, nuevo = seguro(self, clientes.crear_cliente, self.ctx.conn, sesion, **dlg.valores())
        if ok:
            v = dlg.valores()
            self.cliente.setText(" ".join(filter(None, [v["nombre"].strip(), v["apellidos"].strip()])))
            self.cliente_id = nuevo
            self.info_cli.setText("✔ Cliente creado y seleccionado")
            self.filtro.setFocus()

    # --------------------------------------------------------------- guardar
    def limpiar(self):
        self.carrito.limpiar()
        self.descuento.clear()
        self.obs.clear()
        self._quitar_cliente()
        self.cantidad.clear()
        self.filtro.clear()
        self._refrescar_carrito()
        self._fecha_por_defecto()
        self.filtro.setFocus()

    def guardar(self):
        if not self.carrito:
            QMessageBox.information(self, "Oceánica", "Agrega al menos un servicio a la orden.")
            self.filtro.setFocus()
            return
        if self.cliente.text().strip() and self.cliente_id is None:
            r = QMessageBox.question(self, "Cliente sin seleccionar",
                                     "Escribiste un cliente pero no lo elegiste de la lista.\n"
                                     "¿Guardar la orden como venta de mostrador (sin cliente)?")
            if r != QMessageBox.Yes:
                self.cliente.setFocus()
                return
        total = self.carrito.total
        dlg = CobroDialog(self.ctx, self, total, "Anticipo de la orden", permite_cero=True)
        if not dlg.exec():
            return
        pago = dlg.pago
        if pago and not caja.corte_abierto(self.ctx.conn):
            QMessageBox.warning(self, "Caja cerrada", "No hay caja abierta, así que no se puede cobrar.\n"
                                "Abre la caja en la sección «Caja» o guarda la orden sin anticipo.")
            return
        sesion = self.ctx.identificar(self, sensible=True, titulo="Confirma con tu PIN para guardar la orden")
        if not sesion:
            return
        promesa = self.entrega.dateTime().toPython()
        ok, oid = seguro(self, ordenes.crear_orden, self.ctx.conn, sesion, self.carrito.items(), self.cliente_id,
                         promesa, self.carrito.descuento, self.obs.text() or None, pago)
        if not ok:
            return
        orden = ordenes.obtener_orden(self.ctx.conn, oid)
        self.limpiar()
        TicketDialog(self, tickets.ticket_orden_texto(self.ctx.conn, oid), f"{orden['folio']}.pdf",
                     f"Orden {orden['folio']} creada",
                     imprimir=lambda: tickets.imprimir_ticket_orden(self.ctx.conn, oid)).exec()
        self.filtro.setFocus()
