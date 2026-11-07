"""Diálogos reutilizables: identificación por PIN, cobro, cliente y vista de ticket."""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import QRegularExpression, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QFont, QRegularExpressionValidator
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout)

from ..config import RAIZ
from ..seguridad import ErrorAcceso, autenticar_pin
from ..servicios import caja, facturacion, tickets, usuarios
from ..servicios.comunes import ErrorNegocio
from .util import a_decimal, dinero, etiqueta, seguro


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
    """Elige al empleado y valida su PIN. Deja la sesión en self.sesion."""

    def __init__(self, ctx, parent, titulo: str = "¿Quién realiza esto?"):
        super().__init__(parent)
        self.ctx, self.sesion = ctx, None
        self.setWindowTitle("Identificación")
        self.setModal(True)
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(etiqueta(titulo, "subtitulo"))
        ok, filas = seguro(parent, usuarios.listar_para_pin, ctx.conn)
        filas = filas or []
        self.combo = QComboBox()
        for f in filas:
            self.combo.addItem(("●  " if f["presente"] else "     ") + f["nombre"], f["usuario_id"])
        if ctx.ultimo_usuario_id is not None:
            i = self.combo.findData(ctx.ultimo_usuario_id)
            if i >= 0:
                self.combo.setCurrentIndex(i)
        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.Password)
        self.pin.setMaxLength(6)
        self.pin.setPlaceholderText("PIN")
        self.pin.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,6}")))
        self.pin.returnPressed.connect(self._aceptar)
        self.msg = etiqueta("", "error", True)
        if not filas:
            lay.addWidget(etiqueta("Todavía no hay empleados con PIN. El administrador debe darlos de alta "
                                   "en «Empleados y usuarios».", palabra=True))
        else:
            lay.addWidget(etiqueta("Empleado  (● = ya registró su llegada hoy)", "suave"))
            lay.addWidget(self.combo)
            lay.addWidget(etiqueta("PIN", "suave"))
            lay.addWidget(self.pin)
            lay.addWidget(self.msg)
        bb = _botones(self, "Continuar")
        bb.accepted.connect(self._aceptar)
        bb.button(QDialogButtonBox.Ok).setEnabled(bool(filas))
        lay.addWidget(bb)
        (self.pin if ctx.ultimo_usuario_id is not None and filas else self.combo).setFocus()

    def _aceptar(self):
        if self.combo.currentData() is None:
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


class CobroDialog(QDialog):
    """Captura de un pago. Resultado en self.pago = {'metodo_pago_id','monto','referencia'} o None (sin pago)."""

    def __init__(self, ctx, parent, importe: Decimal, titulo: str, permite_cero: bool, texto_importe: str = "Total"):
        super().__init__(parent)
        self.pago, self.importe, self.permite_cero = None, Decimal(importe), permite_cero
        self.setWindowTitle(titulo)
        self.setModal(True)
        self.setMinimumWidth(400)
        self.metodos = {m["id"]: m for m in caja.listar_metodos(ctx.conn)}
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(etiqueta(titulo, "subtitulo"))
        lay.addWidget(etiqueta(f"{texto_importe}: {dinero(importe)}", "titulo"))
        form = QFormLayout()
        self.metodo = QComboBox()
        for m in self.metodos.values():
            self.metodo.addItem(m["nombre"], m["id"])
        self.monto = QLineEdit("" if permite_cero else f"{importe:.2f}")
        self.monto.setPlaceholderText("0.00")
        self.todo = QPushButton("Pagar todo")
        fila = QHBoxLayout()
        fila.addWidget(self.monto, 1)
        fila.addWidget(self.todo)
        self.recibido = QLineEdit()
        self.recibido.setPlaceholderText("Con cuánto paga")
        self.cambio = etiqueta("", "subtitulo")
        self.referencia = QLineEdit()
        self.referencia.setPlaceholderText("Clave de rastreo (si la tiene)")
        self.captura = QCheckBox("Me mostraron la captura de pantalla del comprobante")
        form.addRow("Método", self.metodo)
        form.addRow("Monto a cobrar", fila)
        self.f_recibido = QLabel("Recibido")
        form.addRow(self.f_recibido, self.recibido)
        self.f_cambio = QLabel("Cambio")
        form.addRow(self.f_cambio, self.cambio)
        self.f_ref = QLabel("Clave de rastreo")
        form.addRow(self.f_ref, self.referencia)
        self.f_captura = QLabel("")
        form.addRow(self.f_captura, self.captura)
        lay.addLayout(form)
        self.msg = etiqueta("", "error", True)
        lay.addWidget(self.msg)
        bb = _botones(self, "Cobrar" if not permite_cero else "Continuar")
        bb.accepted.connect(self._aceptar)
        lay.addWidget(bb)
        self.todo.clicked.connect(lambda: (self.monto.setText(f"{self.importe:.2f}"), self.monto.setFocus()))
        self.metodo.currentIndexChanged.connect(self._ajustar)
        self.monto.textChanged.connect(self._calcular_cambio)
        self.recibido.textChanged.connect(self._calcular_cambio)
        self.monto.returnPressed.connect(self._aceptar)
        self.recibido.returnPressed.connect(self._aceptar)
        self.referencia.returnPressed.connect(self._aceptar)
        self._ajustar()
        self.monto.setFocus()

    def _metodo(self) -> dict:
        return self.metodos[self.metodo.currentData()]

    def _ajustar(self):
        m = self._metodo()
        for w in (self.f_recibido, self.recibido, self.f_cambio, self.cambio):
            w.setVisible(bool(m["es_efectivo"]))
        for w in (self.f_ref, self.referencia, self.f_captura, self.captura):
            w.setVisible(bool(m["requiere_confirmacion"]))
        self._calcular_cambio()

    def _calcular_cambio(self):
        monto, recibido = a_decimal(self.monto.text()), a_decimal(self.recibido.text())
        self.cambio.setText(dinero(recibido - monto) if monto is not None and recibido is not None and recibido >= monto else "—")

    def _aceptar(self):
        monto = a_decimal(self.monto.text()) if self.monto.text().strip() else Decimal(0)
        if monto is None or monto < 0:
            self.msg.setText("Escribe un monto válido.")
            return
        if monto > self.importe:
            self.msg.setText(f"El monto no puede ser mayor a {dinero(self.importe)}.")
            return
        if monto == 0:
            if not self.permite_cero:
                self.msg.setText("El monto debe ser mayor que cero.")
                return
            self.pago = None
            return self.accept()
        m = self._metodo()
        ref = self.referencia.text().strip()
        if m["requiere_confirmacion"] and not ref and not self.captura.isChecked():
            self.msg.setText("Pide la captura de pantalla del comprobante (o anota la clave de rastreo).")
            self.referencia.setFocus()
            return
        if m["requiere_confirmacion"] and not ref:
            ref = "CAPTURA DE PANTALLA"  # la encargada confirma después en el banco
        self.pago = {"metodo_pago_id": m["id"], "monto": monto, "referencia": ref or None}
        self.accept()


class ClienteDialog(QDialog):
    def __init__(self, parent, datos: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Cliente")
        self.setMinimumWidth(460)
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

        # Datos fiscales: opcionales; solo para los clientes que piden factura.
        form.addRow(etiqueta("Datos para factura (solo si el cliente la pide; vienen en su constancia fiscal)", "suave", True))
        self.rfc = QLineEdit(d.get("rfc") or "")
        self.rfc.setMaxLength(15)
        self.rfc.setPlaceholderText("12 o 13 caracteres")
        self.rfc.textEdited.connect(self._rfc_mayusculas)
        self.razon_social = QLineEdit(d.get("razon_social") or "")
        self.razon_social.setPlaceholderText("Tal como aparece en la constancia")
        self.regimen = QComboBox()
        self.regimen.addItem("— Sin dato —", None)
        for clave, nombre in facturacion.REGIMENES.items():
            self.regimen.addItem(f"{clave} · {nombre}", clave)
        self.regimen.setCurrentIndex(max(0, self.regimen.findData(d.get("regimen_fiscal"))))
        self.uso = QComboBox()
        self.uso.addItem("— Sin dato —", None)
        for clave, nombre in facturacion.USOS_CFDI.items():
            self.uso.addItem(f"{clave} · {nombre}", clave)
        self.uso.setCurrentIndex(max(0, self.uso.findData(d.get("uso_cfdi"))))
        for combo in (self.regimen, self.uso):  # los nombres del SAT son largos: que no ensanchen el diálogo
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(28)
        self.cp = QLineEdit(d.get("codigo_postal_fiscal") or "")
        self.cp.setMaxLength(5)
        self.cp.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,5}")))
        for etiq, w in (("RFC", self.rfc), ("Razón social", self.razon_social), ("Régimen fiscal", self.regimen),
                        ("Uso del CFDI", self.uso), ("C.P. fiscal", self.cp)):
            form.addRow(etiq, w)
        lay.addLayout(form)
        self.msg = etiqueta("", "error", True)
        lay.addWidget(self.msg)
        bb = _botones(self, "Guardar")
        bb.accepted.connect(self._aceptar)
        lay.addWidget(bb)
        self.nombre.setFocus()

    def _rfc_mayusculas(self, t: str):
        pos = self.rfc.cursorPosition()
        self.rfc.setText(t.upper())
        self.rfc.setCursorPosition(pos)

    def _aceptar(self):
        """Revisa aquí lo que el servicio va a rechazar, para no perder lo capturado si algo está mal."""
        if not self.nombre.text().strip():
            self.msg.setText("Escribe el nombre del cliente.")
            return self.nombre.setFocus()
        if self.email.text().strip() and "@" not in self.email.text():
            self.msg.setText("El correo no es válido.")
            return self.email.setFocus()
        try:
            facturacion.validar_datos_fiscales({k: v for k, v in self.valores().items() if k in facturacion.CAMPOS_FISCALES})
        except ErrorNegocio as e:
            self.msg.setText(str(e))
            return
        self.accept()

    def valores(self) -> dict:
        return {"nombre": self.nombre.text(), "apellidos": self.apellidos.text(), "telefono": self.telefono.text(),
                "email": self.email.text(), "notas": self.notas.text(), "rfc": self.rfc.text(),
                "razon_social": self.razon_social.text(), "regimen_fiscal": self.regimen.currentData(),
                "uso_cfdi": self.uso.currentData(), "codigo_postal_fiscal": self.cp.text()}


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
