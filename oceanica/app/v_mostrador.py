"""Nueva orden: botones grandes por categoría (pensado para pantalla táctil y para quien no usa mucho la computadora).

Flujo: «Ropa por kilo» abre un teclado para los kilos; las demás categorías muestran sus opciones con precio
y cada toque agrega una pieza. La búsqueda por teclado (F2) sigue disponible para quien la prefiera.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from PySide6.QtCore import QStringListModel, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QCompleter, QDateTimeEdit, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from ..servicios import caja, catalogo, clientes, configuracion, facturacion, ordenes, tickets
from .botones import COLORES, BotonGrande, KilosDialog, es_categoria_kilo, icono_para, normalizar
from . import tema
from .carrito import Carrito
from .iconos import en_buscador, icono, poner
from .cobro import CobroDialog
from .dialogos import ClienteDialog, TicketDialog
from .util import a_decimal, cantidad_txt, chip, crear_tabla, dinero, etiqueta, poblar, seguro, tarjeta

DETALLE_KILO = "Playeras, ropa interior, sudaderas, pantalones y sábanas"
COLUMNAS = 3


def _rejilla_con_scroll() -> tuple[QScrollArea, QGridLayout]:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.NoFrame)
    area.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
    cont = QWidget()
    rej = QGridLayout(cont)
    rej.setContentsMargins(0, 0, 4, 0)
    rej.setSpacing(12)
    area.setWidget(cont)
    return area, rej


def _vaciar(rej: QGridLayout) -> None:
    while rej.count():
        w = rej.takeAt(0).widget()
        if w is not None:
            w.deleteLater()


class MostradorView(QWidget):
    titulo = "Nueva orden"

    def __init__(self, ctx, ir_a_orden=None):
        super().__init__()
        self.setObjectName("pagina")
        self.ctx, self.ir_a_orden = ctx, ir_a_orden
        self.carrito = Carrito()
        self.categorias: list[dict] = []
        self.servicios: list[dict] = []
        self.visibles: list[dict] = []          # opciones que se ven ahora (categoría abierta o búsqueda)
        self.cat_kilo: dict | None = None
        self.cliente_id: int | None = None
        self.datos_clientes: dict[int, dict] = {}
        self.mapa_clientes: dict[str, int] = {}

        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(16, 16, 16, 16)
        raiz.setSpacing(14)

        # ---- izquierda: cliente y botones de servicios
        izq = QVBoxLayout()
        izq.setSpacing(8)
        izq.addWidget(etiqueta("Cliente", "subtitulo"))
        fila_cli = QHBoxLayout()
        self.cliente = QLineEdit()
        self.cliente.setPlaceholderText("Nombre o teléfono (puede dejarlo vacío)")
        self.cliente.setMinimumHeight(40)
        self.modelo_cli = QStringListModel()
        self.completer = QCompleter(self.modelo_cli, self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.cliente.setCompleter(self.completer)
        self.b_nuevo_cli = poner(QPushButton("Cliente nuevo"), "user-plus")
        self.b_nuevo_cli.setMinimumHeight(40)
        self.b_quitar_cli = poner(QPushButton(), "x")
        self.b_quitar_cli.setToolTip("Quitar cliente")
        self.b_quitar_cli.setFixedSize(46, 46)
        self.b_quitar_cli.setStyleSheet("padding: 0; min-height: 0;")
        fila_cli.addWidget(self.cliente, 1)
        fila_cli.addWidget(self.b_nuevo_cli)
        fila_cli.addWidget(self.b_quitar_cli)
        izq.addLayout(fila_cli)
        self.info_cli = etiqueta("", "suave")
        izq.addWidget(self.info_cli)

        fila_busca = QHBoxLayout()
        fila_busca.addWidget(etiqueta("¿Qué trae el cliente?", "subtitulo"), 1)
        self.filtro = QLineEdit()
        self.filtro.setPlaceholderText("Buscar (F2)")
        en_buscador(self.filtro)
        self.filtro.setClearButtonEnabled(True)
        self.filtro.setMaximumWidth(240)
        fila_busca.addWidget(self.filtro)
        izq.addLayout(fila_busca)

        self.pila = QStackedWidget()
        # página 0: inicio (kilo + categorías)
        inicio = QWidget()
        li = QVBoxLayout(inicio)
        li.setContentsMargins(0, 0, 0, 0)
        li.setSpacing(10)
        self.b_kilo = BotonGrande("wash-machine", "Ropa por kilo", DETALLE_KILO, alto=116, destacado=True)
        self.b_kilo.clicked.connect(self.abrir_kilo)
        li.addWidget(self.b_kilo)
        li.addWidget(etiqueta("Por pieza", "subtitulo"))
        area_cat, self.rej_cat = _rejilla_con_scroll()
        li.addWidget(area_cat, 1)
        self.pila.addWidget(inicio)
        # página 1: opciones de una categoría o resultados de búsqueda
        opciones = QWidget()
        lo = QVBoxLayout(opciones)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(10)
        cab = QHBoxLayout()
        self.b_regresar = poner(QPushButton("Regresar"), "arrow-left")
        self.b_regresar.setMinimumSize(150, 48)
        self.b_regresar.setStyleSheet("font-size: 12pt; font-weight: 600;")
        self.b_regresar.clicked.connect(self.ir_inicio)
        self.lb_cat = QLabel()
        self.lb_cat.setStyleSheet("font-size: 16pt; font-weight: 700;")
        cab.addWidget(self.b_regresar)
        cab.addSpacing(8)
        cab.addWidget(self.lb_cat, 1)
        lo.addLayout(cab)
        self.lb_vacio = etiqueta("", "suave", True)
        self.lb_vacio.setAlignment(Qt.AlignCenter)
        self.lb_vacio.setStyleSheet("font-size: 12pt; padding: 30px;")
        lo.addWidget(self.lb_vacio)
        area_op, self.rej_op = _rejilla_con_scroll()
        lo.addWidget(area_op, 1)
        self.pila.addWidget(opciones)
        izq.addWidget(self.pila, 1)

        self.aviso = etiqueta("", "chip_ok")
        self.aviso.setAlignment(Qt.AlignCenter)
        self.aviso.setMinimumHeight(34)
        self.aviso.setVisible(False)
        izq.addWidget(self.aviso)
        raiz.addLayout(izq, 6)

        # ---- derecha: la orden
        der = tarjeta()
        dl = QVBoxLayout(der)
        dl.setContentsMargins(14, 14, 14, 14)
        dl.addWidget(etiqueta("Orden", "subtitulo"))
        self.tabla_carrito = crear_tabla(["Servicio", "Cantidad", "Importe"], derecha=(1, 2))
        self.tabla_carrito.verticalHeader().setDefaultSectionSize(44)
        self.tabla_carrito.setStyleSheet("font-size: 11.5pt;")
        dl.addWidget(self.tabla_carrito, 1)
        fila_q = QHBoxLayout()
        self.b_menos = poner(QPushButton("Quitar 1"), "minus")
        self.b_mas = poner(QPushButton("Agregar 1"), "plus")
        self.b_quitar = poner(QPushButton("Eliminar"), "trash", tema.ERROR)
        self.b_menos.setToolTip("Quita una pieza del servicio seleccionado")
        self.b_mas.setToolTip("Agrega una pieza más del servicio seleccionado")
        self.b_quitar.setToolTip("Elimina de la orden todo el servicio seleccionado (pide confirmación)")
        for b in (self.b_menos, self.b_mas, self.b_quitar):
            b.setMinimumHeight(48)
        self.b_quitar.setProperty("rol", "peligro")
        fila_q.addWidget(self.b_menos)
        fila_q.addWidget(self.b_mas)
        fila_q.addStretch(1)
        fila_q.addWidget(self.b_quitar)
        dl.addLayout(fila_q)
        self.lb_subtotal = etiqueta("", "suave")
        dl.addWidget(self.lb_subtotal)
        self.descuento = QLineEdit()
        self.descuento.setPlaceholderText("Descuento $")
        dl.addWidget(self.descuento)
        self.descuento.setVisible(ctx.es_admin)
        self.lb_total = etiqueta("$0.00", "total")
        self.lb_total.setAlignment(Qt.AlignRight)
        dl.addWidget(self.lb_total)
        fila_f = QHBoxLayout()
        fila_f.addWidget(QLabel("Fecha de entrega"))
        self.entrega = QDateTimeEdit()
        self.entrega.setCalendarPopup(True)
        self.entrega.setDisplayFormat("dd/MM/yyyy HH:mm")
        self.entrega.setMinimumHeight(38)
        fila_f.addWidget(self.entrega, 1)
        dl.addLayout(fila_f)
        self.obs = QLineEdit()
        self.obs.setPlaceholderText("Observaciones (opcional): manchas, botones, etc.")
        self.obs.setMinimumHeight(38)
        dl.addWidget(self.obs)
        # ---- ¿cómo se entrega? recoge en mostrador o servicio a domicilio (con cargo extra)
        fila_e = QHBoxLayout()
        self.b_recoge = poner(QPushButton("Recoge aquí"), "building-store")
        self.b_domicilio = poner(QPushButton("A domicilio"), "truck-delivery")
        for b in (self.b_recoge, self.b_domicilio):
            b.setCheckable(True)
            b.setMinimumHeight(46)
            b.setStyleSheet(f"QPushButton:checked {{ background: #E6F0FF; border: 2px solid {tema.PRIMARIO}; "
                            f"color: {tema.PRIMARIO}; font-weight: 600; }}")
            fila_e.addWidget(b)
        self.b_recoge.setChecked(True)
        dl.addLayout(fila_e)
        self.p_domicilio = QWidget()
        pd = QVBoxLayout(self.p_domicilio)
        pd.setContentsMargins(0, 0, 0, 0)
        pd.setSpacing(6)
        self.direccion = QLineEdit()
        self.direccion.setPlaceholderText("Dirección de entrega (calle, número, colonia, referencias)")
        self.direccion.setMinimumHeight(38)
        self.direccion.addAction(icono("map-pin", "#5B6F86", 20), QLineEdit.LeadingPosition)
        pd.addWidget(self.direccion)
        fila_c = QHBoxLayout()
        fila_c.addWidget(QLabel("Cargo a domicilio  $"))
        self.cargo = QLineEdit()
        self.cargo.setMaximumWidth(120)
        self.cargo.setMinimumHeight(38)
        fila_c.addWidget(self.cargo)
        fila_c.addStretch(1)
        pd.addLayout(fila_c)
        dl.addWidget(self.p_domicilio)
        self.p_domicilio.setVisible(False)
        self.factura = QCheckBox("Requiere &factura  (Alt+F)")
        self.factura.setToolTip("El cliente pide factura. Necesita un cliente; la factura se hace fuera del sistema.")
        self.factura.setMinimumHeight(32)
        dl.addWidget(self.factura)
        fila_b = QHBoxLayout()
        self.b_limpiar = QPushButton("Empezar de nuevo")
        self.b_limpiar.setMinimumHeight(56)
        self.b_guardar = poner(QPushButton("Guardar y cobrar"), "check", "white", 26)
        self.b_guardar.setProperty("rol", "primario")
        self.b_guardar.setMinimumHeight(56)
        self.b_guardar.setStyleSheet("font-size: 14pt;")
        fila_b.addWidget(self.b_limpiar)
        fila_b.addWidget(self.b_guardar, 1)
        dl.addLayout(fila_b)
        raiz.addWidget(der, 4)

        # ---- señales y atajos
        self.filtro.textChanged.connect(self._filtrar)
        self.filtro.returnPressed.connect(self._elegir_primero)
        self.b_menos.clicked.connect(lambda: self._sumar(-1))
        self.b_mas.clicked.connect(lambda: self._sumar(1))
        self.b_quitar.clicked.connect(self._quitar)
        self.tabla_carrito.itemSelectionChanged.connect(self._estado_botones)
        self.tabla_carrito.itemDoubleClicked.connect(lambda *_: self._sumar(0))
        self.b_limpiar.clicked.connect(lambda: self.limpiar(preguntar=True))
        self.b_guardar.clicked.connect(self.guardar)
        self.b_nuevo_cli.clicked.connect(self.nuevo_cliente)
        self.b_quitar_cli.clicked.connect(self._quitar_cliente)
        self.cliente.textEdited.connect(self._buscar_clientes)
        self.completer.activated[str].connect(self._elegir_cliente)
        self.descuento.textChanged.connect(self._refrescar_totales)
        self.b_recoge.clicked.connect(lambda: self.elegir_entrega("mostrador"))
        self.b_domicilio.clicked.connect(lambda: self.elegir_entrega("domicilio"))
        self.cargo.textChanged.connect(self._refrescar_totales)
        self.factura.toggled.connect(lambda _: self._info_cliente())
        for tecla, accion in (("F2", self.filtro.setFocus), ("F3", self.cliente.setFocus), ("F4", self.nuevo_cliente),
                              ("F5", self.guardar), ("Esc", self._escape)):
            QShortcut(QKeySequence(tecla), self, activated=accion)
        QShortcut(QKeySequence(Qt.Key_Delete), self.tabla_carrito, activated=self._quitar,
                  context=Qt.WidgetWithChildrenShortcut)
        self._estado_botones()

    # ---------------------------------------------------------------- datos
    def al_mostrar(self):
        ok, cats = seguro(self, catalogo.listar_categorias, self.ctx.conn)
        ok2, servicios = seguro(self, catalogo.listar_servicios, self.ctx.conn)
        self.categorias = cats or []
        self.servicios = servicios or []
        self._armar_categorias()
        self._fecha_por_defecto()
        self.descuento.setVisible(self.ctx.es_admin)
        self.filtro.clear()
        self.ir_inicio()

    def _de_categoria(self, cat_id: int) -> list[dict]:
        return [s for s in self.servicios if s["categoria_id"] == cat_id]

    def _armar_categorias(self):
        _vaciar(self.rej_cat)
        self.cat_kilo = next((c for c in self.categorias if es_categoria_kilo(c["nombre"])), None)
        self.b_kilo.setVisible(self.cat_kilo is not None)
        if self.cat_kilo:
            kilos = self._de_categoria(self.cat_kilo["id"])
            precio = f"{dinero(kilos[0]['precio'])} el kilo · " if len(kilos) == 1 else ""
            self.b_kilo.lb_detalle.setText(precio + DETALLE_KILO)
        otras = [c for c in self.categorias if c is not self.cat_kilo]
        for i, c in enumerate(otras):
            n = len(self._de_categoria(c["id"]))
            detalle = f"{n} opción" if n == 1 else (f"{n} opciones" if n else "Sin opciones aún")
            b = BotonGrande(icono_para(c["nombre"]), c["nombre"], detalle, COLORES[i % len(COLORES)])
            b.clicked.connect(lambda _=False, c=c: self.abrir_categoria(c))
            self.rej_cat.addWidget(b, i // COLUMNAS, i % COLUMNAS)
        self.rej_cat.setRowStretch(self.rej_cat.rowCount(), 1)

    def _fecha_por_defecto(self):
        try:
            dias = int(configuracion.obtener(self.ctx.conn, "dias_entrega_default", "2") or 2)
        except (ValueError, Exception):
            dias = 2
        d = datetime.now().replace(second=0, microsecond=0) + timedelta(days=dias)
        self.entrega.setDateTime(d)

    # ------------------------------------------------------------ navegación
    def ir_inicio(self):
        self.visibles = []
        self.pila.setCurrentIndex(0)

    def abrir_kilo(self):
        if not self.cat_kilo:
            return
        kilos = self._de_categoria(self.cat_kilo["id"])
        if len(kilos) == 1:
            self.elegir(kilos[0])
        else:
            self.abrir_categoria(self.cat_kilo)

    def abrir_categoria(self, cat: dict):
        self._mostrar_opciones(cat["nombre"], self._de_categoria(cat["id"]),
                               "Todavía no hay opciones en esta categoría.\n"
                               "El administrador las agrega en «Servicios y precios».")

    def _mostrar_opciones(self, titulo: str, servicios: list[dict], vacio: str):
        self.visibles = servicios
        self.lb_cat.setText(titulo)
        _vaciar(self.rej_op)
        self.lb_vacio.setText(vacio)
        self.lb_vacio.setVisible(not servicios)
        orden_cat = {c["id"]: i for i, c in enumerate(self.categorias)}
        for i, s in enumerate(servicios):
            unidad = "por kilo" if s["unidad"] == "kilo" else "por pieza"
            colores = COLORES[orden_cat.get(s["categoria_id"], 0) % len(COLORES)]
            b = BotonGrande("", s["nombre"], f"{dinero(s['precio'])} {unidad}", colores, alto=92)
            b.lb_icono.setVisible(False)
            b.lb_detalle.setStyleSheet("font-size: 12pt; font-weight: 600; color: #0B3C9E; background: transparent;")
            b.clicked.connect(lambda _=False, s=s: self.elegir(s))
            self.rej_op.addWidget(b, i // COLUMNAS, i % COLUMNAS)
        self.rej_op.setRowStretch(self.rej_op.rowCount(), 1)
        self.pila.setCurrentIndex(1)

    def _filtrar(self):
        q = normalizar(self.filtro.text().strip())
        if not q:
            self.ir_inicio()
            return
        encontrados = [s for s in self.servicios if q in normalizar(s["nombre"])]
        self._mostrar_opciones(f"Resultados para «{self.filtro.text().strip()}»", encontrados, "No se encontró nada con ese nombre.")

    def _elegir_primero(self):
        if self.visibles:
            self.elegir(self.visibles[0])

    def _escape(self):
        if self.filtro.text():
            self.filtro.clear()
        elif self.pila.currentIndex() == 1:
            self.ir_inicio()
        else:
            self.limpiar(preguntar=True)

    # ---------------------------------------------------------------- orden
    def pedir_kilos(self, servicio: dict, actual: Decimal | None = None) -> Decimal | None:
        dlg = KilosDialog(self, servicio, actual)
        return dlg.kilos if dlg.exec() else None

    def elegir(self, servicio: dict):
        """Kilo: pide los kilos. Pieza: agrega una pieza en cada toque."""
        if servicio["unidad"] == "kilo":
            kilos = self.pedir_kilos(servicio)
            if kilos is None:
                return
            self.agregar(servicio, kilos)
        else:
            self.agregar(servicio, Decimal(1))

    def agregar(self, servicio: dict, cantidad: Decimal) -> bool:
        ok, _ = seguro(self, self.carrito.agregar, servicio, cantidad)
        if not ok:
            return False
        self._refrescar_carrito()
        fila = next(i for i, l in enumerate(self.carrito.lineas) if l.servicio_id == servicio["id"])
        self.tabla_carrito.selectRow(fila)
        texto = cantidad_txt(cantidad, servicio["unidad"]).replace("pza", "pieza" if cantidad == 1 else "piezas")
        self._avisar(f"Se agregó: {servicio['nombre']} ({texto})")
        return True

    def _avisar(self, texto: str):
        chip(self.aviso, texto, "chip_ok")
        self.aviso.setVisible(True)
        QTimer.singleShot(3000, lambda: self.aviso.setVisible(False) if self.aviso.text() == texto else None)

    def _linea_actual(self) -> int:
        return self.tabla_carrito.currentRow()

    def preguntar_eliminar(self, nombre: str, cantidad: str) -> bool:
        caja_ = QMessageBox(QMessageBox.Question, "Eliminar de la orden",
                            f"¿Está seguro de que desea eliminar «{nombre}» ({cantidad}) de la orden?", parent=self)
        si = caja_.addButton("Sí, eliminar", QMessageBox.DestructiveRole)
        no = caja_.addButton("No", QMessageBox.RejectRole)
        caja_.setDefaultButton(no)
        caja_.exec()
        return caja_.clickedButton() is si

    def _sumar(self, delta: int):
        """Quitar 1 / Agregar 1 en piezas. En kilos (o con doble clic) abre el teclado para cambiar la cantidad.
        Si al quitar una pieza el servicio se queda en cero, se pide confirmación antes de eliminarlo."""
        r = self._linea_actual()
        if not 0 <= r < len(self.carrito.lineas):
            return
        l = self.carrito.lineas[r]
        if delta < 0 and l.unidad == "pieza" and l.cantidad + delta <= 0:
            return self._quitar()
        if l.unidad == "kilo" or delta == 0:
            if l.unidad == "kilo":
                nuevo = self.pedir_kilos({"nombre": l.nombre, "precio": l.precio}, l.cantidad)
            else:
                return
            if nuevo is None:
                return
            seguro(self, self.carrito.fijar, r, nuevo)
        else:
            self.carrito.sumar(r, delta)
        self._refrescar_carrito()
        if r < len(self.carrito.lineas):
            self.tabla_carrito.selectRow(r)

    def _quitar(self):
        """Elimina todo el servicio seleccionado, después de confirmar."""
        r = self._linea_actual()
        if not 0 <= r < len(self.carrito.lineas):
            return
        l = self.carrito.lineas[r]
        cant = cantidad_txt(l.cantidad, l.unidad).replace("pza", "pieza" if l.cantidad == 1 else "piezas")
        if not self.preguntar_eliminar(l.nombre, cant):
            return
        self.carrito.quitar(r)
        self._refrescar_carrito()
        self._avisar(f"Se eliminó: {l.nombre}")

    def _estado_botones(self):
        r = self._linea_actual()
        hay = 0 <= r < len(self.carrito.lineas)
        kilo = hay and self.carrito.lineas[r].unidad == "kilo"
        for b in (self.b_menos, self.b_mas, self.b_quitar):
            b.setEnabled(hay)
        # en kilos no se suma de uno en uno: un solo botón abre el teclado
        self.b_menos.setText("Cambiar kilos" if kilo else "Quitar 1")
        poner(self.b_menos, "pencil" if kilo else "minus")
        self.b_mas.setVisible(not kilo)

    def _refrescar_carrito(self):
        filas = [(i, [l.nombre, cantidad_txt(l.cantidad, l.unidad), dinero(l.importe)])
                 for i, l in enumerate(self.carrito.lineas)]
        poblar(self.tabla_carrito, filas)
        self._refrescar_totales()
        self._estado_botones()

    def elegir_entrega(self, tipo: str):
        domicilio = tipo == "domicilio"
        self.b_recoge.setChecked(not domicilio)
        self.b_domicilio.setChecked(domicilio)
        self.p_domicilio.setVisible(domicilio)
        if domicilio:
            ok, cargo = seguro(self, ordenes.cargo_domicilio_configurado, self.ctx.conn)
            self.cargo.setText(f"{cargo or 0:.2f}")
            self.cargo.setReadOnly(not self.ctx.es_admin)   # el empleado cobra lo que fijó el administrador
            self.cargo.setToolTip("" if self.ctx.es_admin else "Lo fija el administrador en «Configuración».")
            self.direccion.setFocus()
        else:
            self.direccion.clear()
        self._refrescar_totales()

    def es_domicilio(self) -> bool:
        return self.b_domicilio.isChecked()

    def _refrescar_totales(self):
        d = a_decimal(self.descuento.text()) if self.ctx.es_admin else None
        self.carrito.descuento = d if d is not None and d >= 0 else Decimal("0.00")
        c = a_decimal(self.cargo.text()) if self.es_domicilio() else None
        self.carrito.cargo_domicilio = c if c is not None and c >= 0 else Decimal("0.00")
        partes = []
        if self.carrito.descuento or self.carrito.cargo_domicilio:
            partes.append(f"Servicios: {dinero(self.carrito.subtotal)}")
        if self.carrito.descuento:
            partes.append(f"Descuento: -{dinero(self.carrito.descuento)}")
        if self.carrito.cargo_domicilio:
            partes.append(f"Domicilio: {dinero(self.carrito.cargo_domicilio)}")
        self.lb_subtotal.setText("  ·  ".join(partes))
        self.lb_total.setText(dinero(self.carrito.total))

    # -------------------------------------------------------------- cliente
    def _buscar_clientes(self, texto: str):
        self.cliente_id = None
        self._info_cliente()
        if len(texto.strip()) < 2:
            self.modelo_cli.setStringList([])
            return
        ok, filas = seguro(self, clientes.buscar_clientes, self.ctx.conn, texto, True, 10)
        self.mapa_clientes = {}
        self.datos_clientes = {c["id"]: c for c in filas or []}
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
            self._info_cliente("Cliente seleccionado")

    def _info_cliente(self, base: str | None = None):
        """Debajo del cliente: si se eligió y, cuando pide factura, qué datos fiscales le faltan."""
        if base is None:
            base = "Cliente seleccionado" if self.cliente_id else ""
        extra = ""
        if self.factura.isChecked():
            if not self.cliente_id:
                extra = "Para facturar, elija o dé de alta al cliente (F4)."
            else:
                falta = facturacion.faltantes(self.datos_clientes.get(self.cliente_id))
                extra = "Datos de factura completos." if not falta else (
                    "Faltan datos de factura: " + ", ".join(falta) + ". Captúrelos en «Clientes».")
        self.info_cli.setText("  ·  ".join(t for t in (base, extra) if t))

    def _quitar_cliente(self):
        self.cliente.clear()
        self.cliente_id = None
        self._info_cliente()

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
            self.datos_clientes[nuevo] = facturacion.validar_datos_fiscales(
                {k: v[k] for k in facturacion.CAMPOS_FISCALES})
            self._info_cliente("Cliente creado y seleccionado")

    # --------------------------------------------------------------- guardar
    def limpiar(self, preguntar: bool = False):
        if preguntar and self.carrito:
            r = QMessageBox.question(self, "Empezar de nuevo", "¿Borrar todo lo que lleva esta orden?")
            if r != QMessageBox.Yes:
                return
        self.carrito.limpiar()
        self.descuento.clear()
        self.obs.clear()
        self.factura.setChecked(False)
        self.elegir_entrega("mostrador")
        self._quitar_cliente()
        self.filtro.clear()
        self._refrescar_carrito()
        self._fecha_por_defecto()
        self.ir_inicio()

    def guardar(self):
        if not self.carrito:
            QMessageBox.information(self, "Oceánica", "Agregue al menos un servicio a la orden.")
            return
        if self.factura.isChecked() and self.cliente_id is None:
            QMessageBox.information(self, "Factura", "Para facturar, elija al cliente de la lista o dé de alta uno nuevo (F4).\n"
                                    "Si no necesita factura, quite la marca «Requiere factura».")
            self.cliente.setFocus()
            return
        if self.cliente.text().strip() and self.cliente_id is None:
            r = QMessageBox.question(self, "Cliente sin seleccionar",
                                     "Escribió un cliente pero no lo eligió de la lista.\n"
                                     "¿Guardar la orden sin cliente?")
            if r != QMessageBox.Yes:
                self.cliente.setFocus()
                return
        entrega = None
        if self.es_domicilio():
            if not self.direccion.text().strip():
                QMessageBox.information(self, "Oceánica", "Escriba la dirección para el servicio a domicilio.")
                self.direccion.setFocus()
                return
            entrega = {"tipo": "domicilio", "direccion": self.direccion.text().strip(),
                       "cargo": self.carrito.cargo_domicilio}
        total = self.carrito.total
        dlg = CobroDialog(self.ctx, self, total, "Anticipo de la orden", permite_cero=True)
        if not dlg.exec():
            return
        pago = dlg.pago
        if pago and not caja.corte_abierto(self.ctx.conn):
            QMessageBox.warning(self, "Caja cerrada", "No hay caja abierta, así que no se puede cobrar.\n"
                                "Abra la caja en la sección «Caja» o guarde la orden con «Paga al recoger».")
            return
        sesion = self.ctx.identificar(self, sensible=True, titulo="Confirme con su PIN para guardar la orden")
        if not sesion:
            return
        promesa = self.entrega.dateTime().toPython()
        ok, oid = seguro(self, ordenes.crear_orden, self.ctx.conn, sesion, self.carrito.items(), self.cliente_id,
                         promesa, self.carrito.descuento, self.obs.text() or None, pago, entrega,
                         requiere_factura=self.factura.isChecked())
        if not ok:
            return
        orden = ordenes.obtener_orden(self.ctx.conn, oid)
        self.limpiar()
        TicketDialog(self, tickets.ticket_orden_texto(self.ctx.conn, oid), f"{orden['folio']}.pdf",
                     f"Orden {orden['folio']} creada",
                     imprimir=lambda: tickets.imprimir_ticket_orden(self.ctx.conn, oid),
                     logo=tickets.logo_activo(self.ctx.conn)).exec()
