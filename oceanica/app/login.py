"""Pantalla de entrada: mostrador (sin contraseña; cada acción pide PIN) o administrador."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ..seguridad import ErrorAcceso, iniciar_sesion
from ..servicios import usuarios
from ..servicios.comunes import ErrorNegocio
from .util import etiqueta, seguro, tarjeta

RECURSOS = Path(__file__).parent / "recursos"


def logo(tam: int) -> QPixmap:
    return QPixmap(str(RECURSOS / "logo.png")).scaled(tam, tam, Qt.KeepAspectRatio, Qt.SmoothTransformation)


class LoginView(QWidget):
    entrar_mostrador = Signal()
    entrar_admin = Signal(dict)

    def __init__(self, ctx):
        super().__init__()
        self.setObjectName("fondo")
        self.ctx = ctx
        raiz = QHBoxLayout(self)
        raiz.addStretch(1)
        col = QVBoxLayout()
        col.addStretch(1)
        lb_logo = QLabel()
        lb_logo.setPixmap(logo(190))
        lb_logo.setAlignment(Qt.AlignCenter)
        col.addWidget(lb_logo)
        self.lb_nombre = etiqueta(ctx.nombre_negocio or "Oceánica", "titulo")
        self.lb_nombre.setAlignment(Qt.AlignCenter)
        col.addWidget(self.lb_nombre)
        sub = etiqueta("Sistema de gestión de lavandería", "suave")
        sub.setAlignment(Qt.AlignCenter)
        col.addWidget(sub)
        col.addSpacing(18)

        card = tarjeta()
        card.setFixedWidth(400)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(22, 22, 22, 22)
        cl.setSpacing(10)
        self.b_mostrador = QPushButton("Entrar al mostrador")
        self.b_mostrador.setProperty("rol", "primario")
        self.b_mostrador.setMinimumHeight(46)
        cl.addWidget(self.b_mostrador)
        cl.addWidget(etiqueta("Cada cobro, orden o entrega se firma con el PIN de quien la hace.", "suave", True))
        cl.addSpacing(10)
        cl.addWidget(etiqueta("Administrador", "subtitulo"))
        self.usuario = QLineEdit()
        self.usuario.setPlaceholderText("Usuario")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Contraseña")
        self.password.setEchoMode(QLineEdit.Password)
        self.msg = etiqueta("", "error", True)
        self.b_admin = QPushButton("Entrar como administrador")
        for w in (self.usuario, self.password, self.msg, self.b_admin):
            cl.addWidget(w)
        col.addWidget(card, 0, Qt.AlignHCenter)
        col.addStretch(2)
        raiz.addLayout(col)
        raiz.addStretch(1)

        self.b_mostrador.clicked.connect(self.entrar_mostrador.emit)
        self.b_admin.clicked.connect(self._admin)
        self.usuario.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self._admin)

    def al_mostrar(self):
        self.lb_nombre.setText(self.ctx.nombre_negocio or "Oceánica")
        self.usuario.clear()
        self.password.clear()
        self.msg.setText("")
        self.b_mostrador.setFocus()

    def _admin(self):
        try:
            s = iniciar_sesion(self.ctx.conn, self.usuario.text(), self.password.text())
        except ErrorAcceso as e:
            self.msg.setText(str(e))
            self.password.clear()
            self.password.setFocus()
            return
        if s["rol"] != "administrador":
            self.msg.setText("Esta cuenta no es de administrador. Los empleados entran por el mostrador con su PIN.")
            self.password.clear()
            return
        if s["debe_cambiar_password"] and not self._cambiar(s):
            return
        self.password.clear()
        self.entrar_admin.emit(s)

    def _cambiar(self, s: dict) -> bool:
        actual = self.password.text()
        nueva, ok = QInputDialog.getText(self, "Contraseña nueva", "Debes elegir una contraseña nueva (mínimo 8 caracteres, "
                                         "no solo números):", QLineEdit.Password)
        if not ok:
            return False
        return seguro(self, usuarios.cambiar_password, self.ctx.conn, s, actual, nueva)[0]
