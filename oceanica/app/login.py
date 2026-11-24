"""Pantalla de entrada: mostrador (sin contraseña; cada acción pide PIN) o administrador."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import mysql.connector
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QStyle, QStyleOption, QVBoxLayout, QWidget)

from .burbujas import Burbujas
from .efectos import efectos
from .iconos import poner
from .. import instalacion
from ..seguridad import ErrorAcceso, iniciar_sesion
from ..servicios import usuarios
from .util import etiqueta, seguro, tarjeta

RECURSOS = Path(__file__).parent / "recursos"
log = logging.getLogger("oceanica")


def bloq_mayus_activado() -> bool:
    """Solo se puede saber en Windows; en otros sistemas se supone apagado."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.user32.GetKeyState(0x14) & 1)
    except Exception:
        return False


def logo(tam: int) -> QPixmap:
    return QPixmap(str(RECURSOS / "logo.png")).scaled(tam, tam, Qt.KeepAspectRatio, Qt.SmoothTransformation)


class LoginView(QWidget):
    entrar_mostrador = Signal()
    entrar_admin = Signal(dict)

    def __init__(self, ctx):
        super().__init__()
        self.setObjectName("fondo")
        self.ctx = ctx
        self.burbujas = Burbujas(self)
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

        card = self.card = tarjeta()
        card.setFixedWidth(460)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(22, 22, 22, 22)
        cl.setSpacing(10)
        self.b_mostrador = poner(QPushButton("Entrar al mostrador"), "cash-register", "white", 26)
        self.b_mostrador.setProperty("rol", "primario")
        self.b_mostrador.setMinimumHeight(64)
        self.b_mostrador.setStyleSheet("font-size: 15pt;")
        cl.addWidget(self.b_mostrador)
        cl.addWidget(etiqueta("Para empleados. Cada orden, cobro o entrega se confirma con el PIN de quien la realiza.", "suave", True))
        cl.addSpacing(10)
        cl.addWidget(etiqueta("Administrador", "subtitulo"))
        self.usuario = QLineEdit()
        self.usuario.setPlaceholderText("Usuario")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Contraseña")
        self.password.setEchoMode(QLineEdit.Password)
        self.mayus = etiqueta("Bloq Mayús está activado: la contraseña distingue mayúsculas.", "error", True)
        self.mayus.hide()
        self.msg = etiqueta("", "error", True)
        self.b_admin = QPushButton("Entrar como administrador")
        self.b_olvido = QPushButton("¿Olvidó su contraseña?")
        self.b_olvido.setFlat(True)
        self.b_olvido.setCursor(Qt.PointingHandCursor)
        self.b_olvido.setStyleSheet("QPushButton { border: none; color: #2E6AD4; text-decoration: underline; }")
        for w in (self.usuario, self.password, self.mayus, self.msg, self.b_admin, self.b_olvido):
            cl.addWidget(w)
        col.addWidget(card, 0, Qt.AlignHCenter)
        col.addStretch(2)
        raiz.addLayout(col)
        raiz.addStretch(1)

        self.b_mostrador.clicked.connect(self.entrar_mostrador.emit)
        self.b_admin.clicked.connect(self._admin)
        self.b_olvido.clicked.connect(self._olvido)
        self.usuario.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self._admin)
        self.password.textEdited.connect(lambda *_: self._revisar_mayus())
        self.usuario.textEdited.connect(lambda *_: self._revisar_mayus())

    def _revisar_mayus(self):
        self.mayus.setVisible(bloq_mayus_activado())

    # ---- burbujas del fondo
    def paintEvent(self, e):
        p = QPainter(self)
        op = QStyleOption()
        op.initFrom(self)
        self.style().drawPrimitive(QStyle.PE_Widget, op, p, self)  # fondo de la hoja de estilos
        self.burbujas.pintar(p)
        p.end()

    def showEvent(self, e):
        super().showEvent(e)
        self.burbujas.iniciar()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.burbujas.detener()

    def al_mostrar(self):
        self.lb_nombre.setText(self.ctx.nombre_negocio or "Oceánica")
        self.usuario.clear()
        self.password.clear()
        self.msg.setText("")
        self.mayus.hide()
        self.b_mostrador.setFocus()

    def _error(self, texto: str):
        self.msg.setText(texto)
        self.password.clear()
        self.password.setFocus()
        efectos.reproducir("error")
        efectos.sacudir(self.card)

    def _admin(self):
        if not self.usuario.text().strip() or not self.password.text():
            self._error("Escriba su usuario y su contraseña.")
            return
        try:
            s = iniciar_sesion(self.ctx.conn, self.usuario.text(), self.password.text())
        except ErrorAcceso as e:
            mensaje = str(e)
            if bloq_mayus_activado():
                mensaje += " Revise que Bloq Mayús esté apagado."
            self._error(mensaje)
            return
        except mysql.connector.Error:
            log.exception("Error de base de datos al entrar como administrador")
            self._error("No se pudo revisar la cuenta porque la base de datos no responde. "
                        "Reinicie la computadora y vuelva a intentar.")
            return
        if s["rol"] != "administrador":
            self._error("Esta cuenta no es de administrador. Los empleados entran por el mostrador con su PIN.")
            return
        if s["debe_cambiar_password"] and not self._cambiar(s):
            return
        self.password.clear()
        self.entrar_admin.emit(s)

    def _olvido(self):
        dlg = RestablecerAdminDialog(self.ctx.conn, self.usuario.text().strip(), self)
        if dlg.exec():
            self.usuario.setText(dlg.usuario_ok)
            self.password.clear()
            self.password.setFocus()
            self.msg.setText("")

    def _cambiar(self, s: dict) -> bool:
        actual = self.password.text()
        nueva, ok = QInputDialog.getText(self, "Contraseña nueva", "Elija una contraseña nueva (mínimo 8 caracteres, "
                                         "no solo números):", QLineEdit.Password)
        if not ok:
            return False
        return seguro(self, usuarios.cambiar_password, self.ctx.conn, s, actual, nueva)[0]


class RestablecerAdminDialog(QDialog):
    """Restablece la contraseña de una cuenta de administrador. Exige la contraseña de recuperación (root)."""

    def __init__(self, conn, usuario_sugerido: str, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.usuario_ok = usuario_sugerido
        self.setWindowTitle("Restablecer contraseña de administrador")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 22, 22, 22)
        lay.setSpacing(10)
        lay.addWidget(etiqueta("Restablecer contraseña", "titulo"))
        lay.addWidget(etiqueta("Para hacerlo necesita la contraseña de recuperación (la de root que puso al instalar). "
                               "La cuenta quedará con la contraseña nueva y desbloqueada.", "suave", True))
        form = QFormLayout()
        self.usuario = QLineEdit(usuario_sugerido)
        self.recuperacion = QLineEdit(); self.recuperacion.setEchoMode(QLineEdit.Password)
        self.nueva = QLineEdit(); self.nueva.setEchoMode(QLineEdit.Password)
        self.nueva2 = QLineEdit(); self.nueva2.setEchoMode(QLineEdit.Password)
        form.addRow("Usuario del administrador:", self.usuario)
        form.addRow("Contraseña de recuperación:", self.recuperacion)
        form.addRow("Contraseña nueva:", self.nueva)
        form.addRow("Repita la nueva:", self.nueva2)
        lay.addLayout(form)
        fila = QHBoxLayout()
        b_cancelar = QPushButton("Cancelar")
        self.b_ok = QPushButton("Restablecer")
        self.b_ok.setProperty("rol", "primario")
        self.b_ok.setDefault(True)
        fila.addStretch(1); fila.addWidget(b_cancelar); fila.addWidget(self.b_ok)
        lay.addLayout(fila)
        b_cancelar.clicked.connect(self.reject)
        self.b_ok.clicked.connect(self._aplicar)

    def _aplicar(self):
        if self.nueva.text() != self.nueva2.text():
            QMessageBox.warning(self, "Oceánica", "Las contraseñas nuevas no coinciden.")
            return
        try:
            instalacion.restablecer_admin(self.conn, root_actual=self.recuperacion.text(),
                                          usuario=self.usuario.text(), nueva=self.nueva.text())
        except instalacion.ErrorInstalacion as e:
            QMessageBox.warning(self, "Oceánica", str(e))
            return
        except Exception:
            log.exception("Falló el restablecimiento de la contraseña de administrador")
            QMessageBox.critical(self, "Oceánica", "No se pudo restablecer la contraseña. El detalle quedó en la "
                                 "carpeta logs.")
            return
        self.usuario_ok = self.usuario.text().strip()
        QMessageBox.information(self, "Oceánica", f"Listo. Entre como «{self.usuario_ok}» con la contraseña nueva.")
        self.accept()
