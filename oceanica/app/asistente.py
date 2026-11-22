"""Asistente de primera vez: aparece al abrir el programa en una computadora donde todavía no está instalado.

Solo pide lo indispensable; la regla vive en `oceanica.instalacion`.
"""
from __future__ import annotations

import logging

from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox, QPushButton, QVBoxLayout)

from .. import instalacion
from .util import etiqueta

log = logging.getLogger("oceanica")


def _clave() -> QLineEdit:
    c = QLineEdit()
    c.setEchoMode(QLineEdit.Password)
    return c


class AsistenteInstalacion(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Lavandería Oceánica: primera vez")
        self.setMinimumWidth(520)
        self.resultado: dict | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(12)
        lay.addWidget(etiqueta("Bienvenida", "titulo"))
        self.aviso = etiqueta("", None, True)
        lay.addWidget(self.aviso)

        self.form = QFormLayout()
        self.root_actual = _clave()
        self.usuario = QLineEdit("admin")
        self.clave = _clave()
        self.clave2 = _clave()
        self.recuperacion = _clave()
        self.recuperacion2 = _clave()
        self.form.addRow("Contraseña actual de la base (root):", self.root_actual)
        self.form.addRow("Usuario de la encargada:", self.usuario)
        self.form.addRow("Contraseña de la encargada:", self.clave)
        self.form.addRow("Repita la contraseña:", self.clave2)
        self.form.addRow("Contraseña de recuperación:", self.recuperacion)
        self.form.addRow("Repita la de recuperación:", self.recuperacion2)
        lay.addLayout(self.form)
        self.nota = etiqueta("", "suave", True)
        lay.addWidget(self.nota)

        fila = QHBoxLayout()
        self.b_reintentar = QPushButton("Reintentar")
        self.b_salir = QPushButton("Salir")
        self.b_instalar = QPushButton("Instalar")
        self.b_instalar.setProperty("rol", "primario")
        self.b_instalar.setDefault(True)
        fila.addWidget(self.b_reintentar)
        fila.addStretch(1)
        fila.addWidget(self.b_salir)
        fila.addWidget(self.b_instalar)
        lay.addLayout(fila)
        self.b_reintentar.clicked.connect(self.revisar)
        self.b_salir.clicked.connect(self.reject)
        self.b_instalar.clicked.connect(self.instalar)
        self.revisar()

    def _mostrar_fila(self, campo, visible: bool) -> None:
        self.form.setRowVisible(campo, visible)

    def revisar(self) -> None:
        self.estado = instalacion.estado_servidor()
        nuevo = self.estado == instalacion.ROOT_SIN_CONTRASENA
        hay = self.estado != instalacion.SIN_SERVIDOR
        for campo in (self.usuario, self.clave, self.clave2):
            self._mostrar_fila(campo, hay)
        self._mostrar_fila(self.root_actual, self.estado == instalacion.ROOT_CON_CONTRASENA)
        for campo in (self.recuperacion, self.recuperacion2):
            self._mostrar_fila(campo, nuevo)
        self.b_instalar.setVisible(hay)
        self.b_reintentar.setVisible(not hay)
        if not hay:
            self.aviso.setText("No se encontró la base de datos en esta computadora.\n\n"
                               "Si acaba de instalar, espere un momento y presione «Reintentar». "
                               "Si sigue igual, vuelva a ejecutar el instalador de Oceánica.")
            self.nota.setText("")
        elif nuevo:
            self.aviso.setText("Falta un solo paso. Elija el usuario y la contraseña con los que la encargada "
                               "va a entrar al sistema.")
            self.nota.setText("La contraseña de recuperación solo se usa si la encargada olvida la suya "
                              "(menú Inicio → «Restablecer contraseña de administrador»). Anótela en papel y "
                              "guárdela fuera de la computadora: sin ella no se puede recuperar la cuenta.")
        else:
            self.aviso.setText("Esta computadora ya tiene una base de datos. Escriba su contraseña de root "
                               "(no se guarda) y los datos de la encargada.")
            self.nota.setText("Si en esa base ya existe una encargada, se conserva y los datos de arriba no se usan.")

    def instalar(self) -> None:
        if self.clave.text() != self.clave2.text():
            QMessageBox.warning(self, "Oceánica", "Las contraseñas de la encargada no coinciden.")
            return
        nuevo = self.estado == instalacion.ROOT_SIN_CONTRASENA
        if nuevo and self.recuperacion.text() != self.recuperacion2.text():
            QMessageBox.warning(self, "Oceánica", "Las contraseñas de recuperación no coinciden.")
            return
        try:
            self.resultado = instalacion.instalar(
                root_actual="" if nuevo else self.root_actual.text(),
                nueva_root=self.recuperacion.text() if nuevo else None,
                usuario_admin=self.usuario.text(), password_admin=self.clave.text())
        except instalacion.ErrorInstalacion as e:
            QMessageBox.warning(self, "Oceánica", str(e))
            return
        except Exception:
            log.exception("Falló la instalación desde el asistente")
            QMessageBox.critical(self, "Oceánica", "No se pudo terminar la instalación. "
                                 "El detalle quedó en la carpeta logs.")
            return
        if self.resultado["admin_creado"]:
            texto = f"Listo. Entre con el usuario «{self.usuario.text().strip()}» y su contraseña."
        else:
            texto = "Listo. La base ya tenía una encargada: entre con su usuario de siempre."
        QMessageBox.information(self, "Oceánica", texto)
        self.accept()
