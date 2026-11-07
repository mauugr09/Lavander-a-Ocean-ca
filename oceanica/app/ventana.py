"""Ventana principal: barra superior, navegación y páginas según el modo."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget, QMainWindow, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..servicios import caja, configuracion
from .login import LoginView, logo
from .util import chip, etiqueta, fecha_hora
from .v_asistencia import AsistenciaView
from .v_caja import CajaView
from .v_catalogo import CatalogoView
from .v_clientes import ClientesView
from .v_config import ConfigView
from .v_mostrador import MostradorView
from .v_ordenes import OrdenesView
from .v_inventario import InventarioView
from .v_nomina import NominaView
from .v_personal import PersonalView
from .v_reportes import ReportesView
from .v_transferencias import TransferenciasView

INACTIVIDAD_ADMIN_MS = 10 * 60 * 1000  # el administrador se cierra solo tras 10 min sin tocar nada


class _Actividad(QObject):
    def __init__(self, ventana):
        super().__init__(ventana)
        self.ventana = ventana

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.MouseButtonPress, QEvent.KeyPress, QEvent.MouseMove):
            self.ventana.reiniciar_inactividad()
        return False


class Ventana(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("Oceánica Gestión")
        self.setMinimumSize(1100, 660)
        self.pila = QStackedWidget()
        self.setCentralWidget(self.pila)
        self.login = LoginView(ctx)
        self.login.entrar_mostrador.connect(lambda: self.abrir_shell(None))
        self.login.entrar_admin.connect(self.abrir_shell)
        self.pila.addWidget(self.login)
        self.shell: QWidget | None = None
        self.paginas: list = []
        self.timer_caja = QTimer(self)
        self.timer_caja.timeout.connect(self.refrescar_estado)
        self.timer_inact = QTimer(self)
        self.timer_inact.setSingleShot(True)
        self.timer_inact.timeout.connect(self.cerrar_sesion)
        self.filtro = _Actividad(self)
        self.mostrar_login()

    # ------------------------------------------------------------ navegación
    def mostrar_login(self):
        self.timer_caja.stop()
        self.timer_inact.stop()
        self.ctx.admin = None
        self.ctx.olvidar_identidad()
        if self.shell is not None:
            self.pila.removeWidget(self.shell)
            self.shell.deleteLater()
            self.shell, self.paginas = None, []
        self.pila.setCurrentWidget(self.login)
        self.login.al_mostrar()

    def abrir_shell(self, sesion_admin):
        self.ctx.admin = sesion_admin
        self.ctx.nombre_negocio = configuracion.obtener(self.ctx.conn, "negocio_nombre", "") or "Oceánica"
        self.shell = QWidget()
        self.shell.setObjectName("fondo")
        raiz = QHBoxLayout(self.shell)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        paginas = [MostradorView(self.ctx), OrdenesView(self.ctx), CajaView(self.ctx), ClientesView(self.ctx), AsistenciaView(self.ctx),
                   InventarioView(self.ctx)]
        if sesion_admin:
            paginas += [ReportesView(self.ctx), NominaView(self.ctx), CatalogoView(self.ctx), PersonalView(self.ctx), TransferenciasView(self.ctx),
                        ConfigView(self.ctx)]
        self.paginas = paginas

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(220)
        self.nav.setFocusPolicy(Qt.NoFocus)
        for i, p in enumerate(paginas):
            self.nav.addItem(f"{p.titulo}")
            if i < 9:
                QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self.shell, activated=lambda i=i: self.nav.setCurrentRow(i))
        raiz.addWidget(self.nav)

        der = QVBoxLayout()
        der.setSpacing(0)
        barra = QFrame()
        barra.setObjectName("barra")
        bl = QHBoxLayout(barra)
        bl.setContentsMargins(14, 6, 14, 6)
        lb = QLabel()
        lb.setPixmap(logo(38))
        bl.addWidget(lb)
        bl.addWidget(etiqueta(self.ctx.nombre_negocio, "subtitulo"))
        bl.addStretch(1)
        self.chip_caja = QLabel()
        self.chip_modo = QLabel()
        chip(self.chip_modo, f"Administrador: {sesion_admin['usuario']}" if sesion_admin else "Modo mostrador", "chip_neutro")
        b_salir = QPushButton("Salir")
        b_salir.clicked.connect(self.cerrar_sesion)
        for w in (self.chip_caja, self.chip_modo, b_salir):
            bl.addWidget(w)
        der.addWidget(barra)
        self.contenido = QStackedWidget()
        for p in paginas:
            self.contenido.addWidget(p)
        der.addWidget(self.contenido, 1)
        raiz.addLayout(der, 1)

        self.nav.currentRowChanged.connect(self._cambiar_pagina)
        self.pila.addWidget(self.shell)
        self.pila.setCurrentWidget(self.shell)
        self.nav.setCurrentRow(0)
        self.timer_caja.start(20000)
        self.refrescar_estado()
        if sesion_admin:
            self.reiniciar_inactividad()
            from PySide6.QtWidgets import QApplication
            QApplication.instance().installEventFilter(self.filtro)

    def _cambiar_pagina(self, fila: int):
        if 0 <= fila < len(self.paginas):
            self.contenido.setCurrentIndex(fila)
            self.paginas[fila].al_mostrar()
            self.refrescar_estado()

    def ir_a(self, titulo: str):
        for i, p in enumerate(self.paginas):
            if p.titulo == titulo:
                self.nav.setCurrentRow(i)

    def refrescar_estado(self):
        try:
            corte = caja.corte_abierto(self.ctx.conn)
            if corte:
                chip(self.chip_caja, f"Caja abierta desde {fecha_hora(corte['abierta_en'])[-5:]}", "chip_ok")
            else:
                chip(self.chip_caja, "Caja cerrada", "chip_alerta")
            if self.ctx.es_admin:
                from ..seguridad import ErrorAcceso  # noqa: F401
                n = len(caja.listar_transferencias_pendientes(self.ctx.conn, self.ctx.admin))
                for i, p in enumerate(self.paginas):
                    if p.titulo == "Transferencias":
                        self.nav.item(i).setText(f"Transferencias ({n})" if n else "Transferencias")
        except Exception:  # el estado es informativo: si falla la consulta no se interrumpe al usuario
            pass

    # -------------------------------------------------------------- sesión
    def reiniciar_inactividad(self):
        if self.ctx.es_admin:
            self.timer_inact.start(INACTIVIDAD_ADMIN_MS)

    def cerrar_sesion(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance().removeEventFilter(self.filtro)
        self.mostrar_login()
