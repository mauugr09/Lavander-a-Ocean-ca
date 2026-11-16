"""Diálogos reutilizables: identificación por PIN, cobro, cliente y vista de ticket."""
from __future__ import annotations

from PySide6.QtCore import QRegularExpression, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QRegularExpressionValidator
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout)

from ..config import RAIZ
from ..seguridad import ErrorAcceso, autenticar_pin
from ..servicios import tickets, usuarios
from .botones import Teclado
from .iconos import poner
from .cobro import CobroDialog  # noqa: F401  (se usa desde las pantallas como dialogos.CobroDialog)
from .tema import PRIMARIO
from .util import etiqueta, seguro


def _botones(dlg: QDialog, texto_ok: str = "Aceptar", primario: bool = True) -> QDialogButtonBox:
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    ok = bb.button(QDialogButtonBox.Ok)
    ok.setText(texto_ok)
    if primario:
        ok.setProperty("rol", "primario")
    bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
    bb.rejected.connect(dlg.reject)
    return bb


class PinDialog(QDialog):
    """Elige al empleado (botón con su nombre) y valida su PIN con teclado grande. Sesión en self.sesion."""

    def __init__(self, ctx, parent, titulo: str = "¿Quién realiza esto?"):
        super().__init__(parent)
        self.ctx, self.sesion = ctx, None
        self.setWindowTitle("Identificación")
        self.setModal(True)
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(12)
        lay.addWidget(etiqueta(titulo, "titulo"))
        ok, filas = seguro(parent, usuarios.listar_para_pin, ctx.conn)
        filas = filas or []
        self.combo = QComboBox()  # guarda la elección; en pantalla se elige con los botones
        self.combo.setVisible(False)
        self.botones: list[QPushButton] = []
        self.grupo = QButtonGroup(self)
        self.grupo.setExclusive(True)
        self.msg = etiqueta("", "error", True)
        self.msg.setStyleSheet("font-size: 13pt;")
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(18)
        if not filas:
            lay.addWidget(etiqueta("Todavía no hay empleados con PIN. El administrador debe darlos de alta "
                                   "en «Empleados y usuarios».", palabra=True))
            self.pin = QLineEdit()
        else:
            izq = QVBoxLayout()
            izq.addWidget(etiqueta("1. Toque su nombre", "subtitulo"))
            for i, f in enumerate(filas):
                self.combo.addItem(f["nombre"], f["usuario_id"])
                b = QPushButton(f["nombre"] + ("\n(ya registró su llegada)" if f["presente"] else ""))
                b.setCheckable(True)
                b.setMinimumHeight(64)
                b.setStyleSheet(f"QPushButton {{ font-size: 13pt; font-weight: 600; text-align: left; padding: 8px 16px; }}"
                                f"QPushButton:checked {{ background: {PRIMARIO}; color: white; border: none; }}")
                b.clicked.connect(lambda _=False, i=i: self._elegir(i))
                self.grupo.addButton(b)
                self.botones.append(b)
                izq.addWidget(b)
            izq.addStretch(1)
            cuerpo.addLayout(izq, 1)
            der = QVBoxLayout()
            der.addWidget(etiqueta("2. Escriba su PIN", "subtitulo"))
            self.teclado = Teclado(con_punto=False, alto_tecla=56)
            self.pin = self.teclado.pantalla
            self.pin.setEchoMode(QLineEdit.Password)
            self.pin.setPlaceholderText("")
            der.addWidget(self.teclado)
            cuerpo.addLayout(der, 1)
            lay.addLayout(cuerpo)
            lay.addWidget(self.msg)
        self.pin.setMaxLength(6)
        self.pin.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,6}")))
        self.pin.returnPressed.connect(self._aceptar)
        pie = QHBoxLayout()
        cancelar = QPushButton("Cancelar")
        cancelar.setMinimumHeight(52)
        self.b_ok = poner(QPushButton("Continuar"), "check", "white")
        self.b_ok.setProperty("rol", "primario")
        self.b_ok.setMinimumHeight(52)
        self.b_ok.setStyleSheet("font-size: 14pt;")
        self.b_ok.setEnabled(bool(filas))
        pie.addWidget(cancelar, 1)
        pie.addWidget(self.b_ok, 2)
        lay.addLayout(pie)
        cancelar.clicked.connect(self.reject)
        self.b_ok.clicked.connect(self._aceptar)
        if filas:
            i = self.combo.findData(ctx.ultimo_usuario_id) if ctx.ultimo_usuario_id is not None else -1
            if i < 0 and len(filas) == 1:
                i = 0
            if i >= 0:
                self._elegir(i)
            self.pin.setFocus()

    def _elegir(self, i: int):
        self.combo.setCurrentIndex(i)
        self.botones[i].setChecked(True)
        self.msg.setText("")
        self.pin.setFocus()

    def _aceptar(self):
        if not self.botones or not any(b.isChecked() for b in self.botones):
            self.msg.setText("Primero toque su nombre.")
            return
        if not self.pin.text():
            self.msg.setText("Escriba su PIN.")
            return
        try:
            self.sesion = autenticar_pin(self.ctx.conn, self.combo.currentData(), self.pin.text())
        except ErrorAcceso as e:
            self.msg.setText(str(e))
            self.pin.clear()
            self.pin.setFocus()
            return
        self.accept()


class AutorizacionDialog(QDialog):
    """La encargada (administrador) autoriza una excepción con su usuario y contraseña. Sesión en self.sesion."""

    def __init__(self, ctx, parent, titulo: str):
        super().__init__(parent)
        self.ctx, self.sesion = ctx, None
        self.setWindowTitle("Autorización de la encargada")
        self.setModal(True)
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.addWidget(etiqueta(titulo, "subtitulo", True))
        self.usuario, self.password = QLineEdit(), QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.usuario.setPlaceholderText("Usuario del administrador")
        self.password.setPlaceholderText("Contraseña")
        self.password.returnPressed.connect(self._aceptar)
        self.msg = etiqueta("", "error", True)
        for w in (self.usuario, self.password, self.msg):
            lay.addWidget(w)
        bb = _botones(self, "Autorizar")
        bb.accepted.connect(self._aceptar)
        lay.addWidget(bb)
        self.usuario.setFocus()

    def _aceptar(self):
        from ..seguridad import ErrorAcceso, iniciar_sesion
        try:
            s = iniciar_sesion(self.ctx.conn, self.usuario.text(), self.password.text())
        except ErrorAcceso as e:
            self.msg.setText(str(e))
            self.password.clear()
            return
        if s["rol"] != "administrador":
            self.msg.setText("Esa cuenta no es de administrador.")
            self.password.clear()
            return
        self.sesion = s
        self.accept()


class ClienteDialog(QDialog):
    def __init__(self, parent, datos: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Cliente")
        self.setMinimumWidth(420)
        d = datos or {}
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.nombre = QLineEdit(d.get("nombre") or "")
        self.apellidos = QLineEdit(d.get("apellidos") or "")
        self.telefono = QLineEdit(d.get("telefono") or "")
        self.email = QLineEdit(d.get("email") or "")
        self.notas = QLineEdit(d.get("notas") or "")
        for etiq, w in (("Nombre *", self.nombre), ("Apellidos", self.apellidos), ("Teléfono", self.telefono),
                        ("Correo", self.email), ("Notas", self.notas)):
            form.addRow(etiq, w)
        lay.addLayout(form)
        bb = _botones(self, "Guardar")
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)
        self.nombre.setFocus()

    def valores(self) -> dict:
        return {"nombre": self.nombre.text(), "apellidos": self.apellidos.text(), "telefono": self.telefono.text(),
                "email": self.email.text(), "notas": self.notas.text()}


class TicketDialog(QDialog):
    """Vista previa del ticket con impresión directa (Windows) o PDF."""

    def __init__(self, parent, texto: str, nombre_pdf: str, titulo: str = "Ticket", imprimir=None):
        super().__init__(parent)
        self.texto, self.nombre_pdf, self._imprimir = texto, nombre_pdf, imprimir
        self.setWindowTitle(titulo)
        lay = QVBoxLayout(self)
        vista = QPlainTextEdit(texto)
        vista.setReadOnly(True)
        fuente = QFont("Consolas")
        fuente.setStyleHint(QFont.Monospace)
        vista.setFont(fuente)
        vista.setMinimumSize(460, 420)
        lay.addWidget(vista)
        fila = QHBoxLayout()
        b_imp = QPushButton("Imprimir")
        b_imp.setProperty("rol", "primario")
        b_imp.setEnabled(imprimir is not None)
        b_pdf = QPushButton("Abrir PDF")
        b_cerrar = QPushButton("Cerrar")
        fila.addWidget(b_imp)
        fila.addWidget(b_pdf)
        fila.addStretch(1)
        fila.addWidget(b_cerrar)
        lay.addLayout(fila)
        b_imp.clicked.connect(self._imprimir_ahora)
        b_pdf.clicked.connect(self.abrir_pdf)
        b_cerrar.clicked.connect(self.accept)
        b_cerrar.setDefault(True)

    def generar_pdf(self):
        return tickets.texto_a_pdf_ticket(self.texto, RAIZ / "tickets" / self.nombre_pdf)

    def abrir_pdf(self):
        ruta = self.generar_pdf()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(ruta)))

    def _imprimir_ahora(self):
        try:
            self._imprimir()
        except tickets.ErrorImpresion as e:
            if QMessageBox.question(self, "Impresión", f"{e}\n\n¿Abrir el PDF para imprimirlo desde ahí?") == QMessageBox.Yes:
                self.abrir_pdf()
