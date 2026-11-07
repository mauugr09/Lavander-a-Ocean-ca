"""Empleados y accesos (administrador): alta con PIN, cambio de PIN y bajas."""
from __future__ import annotations

import secrets
from datetime import date

from PySide6.QtCore import QDate, QRegularExpression, QTime
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (QCheckBox, QDateEdit, QGridLayout, QTimeEdit, QDialog, QFormLayout, QHBoxLayout, QInputDialog, QLineEdit, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from ..seguridad import validar_pin
from ..servicios import empleados, usuarios
from .dialogos import _botones
from .util import crear_tabla, etiqueta, id_seleccionado, poblar, seguro


def pin_aleatorio() -> str:
    while True:
        pin = "".join(secrets.choice("0123456789") for _ in range(6))
        if not validar_pin(pin):
            return pin


class EmpleadoDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Nuevo empleado")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.nombre, self.apellidos = QLineEdit(), QLineEdit()
        self.telefono, self.puesto = QLineEdit(), QLineEdit()
        self.ingreso = QDateEdit(QDate.currentDate())
        self.ingreso.setCalendarPopup(True)
        self.ingreso.setDisplayFormat("dd/MM/yyyy")
        self.pin = QLineEdit(pin_aleatorio())
        self.pin.setMaxLength(6)
        self.pin.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,6}")))
        otro = QPushButton("Otro")
        fila_pin = QHBoxLayout()
        fila_pin.addWidget(self.pin, 1)
        fila_pin.addWidget(otro)
        for etiq, w in (("Nombre *", self.nombre), ("Apellidos *", self.apellidos), ("Teléfono", self.telefono),
                        ("Puesto", self.puesto), ("Fecha de ingreso", self.ingreso)):
            form.addRow(etiq, w)
        form.addRow("PIN de mostrador", fila_pin)
        lay.addLayout(form)
        lay.addWidget(etiqueta("Dile su PIN al empleado en persona. Puede cambiarlo después.", "suave", True))
        bb = _botones(self, "Guardar")
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)
        otro.clicked.connect(lambda: self.pin.setText(pin_aleatorio()))
        self.nombre.setFocus()


DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
PLANTILLAS = {"Matutino (L-V 9:00 a 15:00, sábado 9:00 a 17:00)": ("09:00", "15:00"),
              "Vespertino (L-V 12:00 a 18:00, sábado 9:00 a 17:00)": ("12:00", "18:00")}


def _hhmm(t: QTime) -> str:
    return t.toString("HH:mm")


class HorarioDialog(QDialog):
    """Horario semanal de un empleado: qué días trabaja y de qué hora a qué hora. Los días sin marcar son su descanso."""

    def __init__(self, parent, nombre: str, actuales: dict[int, tuple[str, str]]):
        super().__init__(parent)
        self.setWindowTitle(f"Horario de {nombre}")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.addWidget(etiqueta("Marca los días que trabaja. Los demás son su descanso (no cuentan como falta).", "suave", True))
        rejilla = QGridLayout()
        self.filas: list[tuple[QCheckBox, QTimeEdit, QTimeEdit]] = []
        for i, dia in enumerate(DIAS):
            c, e, s = QCheckBox(dia), QTimeEdit(), QTimeEdit()
            for w in (e, s):
                w.setDisplayFormat("HH:mm")
            ent, sal = actuales.get(i + 1, ("09:00", "15:00"))
            c.setChecked(i + 1 in actuales)
            e.setTime(QTime.fromString(ent, "HH:mm"))
            s.setTime(QTime.fromString(sal, "HH:mm"))
            rejilla.addWidget(c, i, 0)
            rejilla.addWidget(e, i, 1)
            rejilla.addWidget(etiqueta("a"), i, 2)
            rejilla.addWidget(s, i, 3)
            self.filas.append((c, e, s))
        lay.addLayout(rejilla)
        lay.addWidget(etiqueta("Llenar rápido:", "suave"))
        for texto, (ent, sal) in PLANTILLAS.items():
            b = QPushButton(texto)
            b.clicked.connect(lambda _=False, ent=ent, sal=sal: self.plantilla(ent, sal))
            lay.addWidget(b)
        lay.addWidget(_botones(self, "Guardar horario"))

    def plantilla(self, ent: str, sal: str):
        for i, (c, e, s) in enumerate(self.filas):
            if i < 5:
                c.setChecked(True)
                e.setTime(QTime.fromString(ent, "HH:mm"))
                s.setTime(QTime.fromString(sal, "HH:mm"))
            elif i == 5:
                c.setChecked(True)
                e.setTime(QTime(9, 0))
                s.setTime(QTime(17, 0))
            else:
                c.setChecked(False)

    def turnos(self) -> list[tuple[int, str, str]]:
        return [(i + 1, _hhmm(e.time()), _hhmm(s.time())) for i, (c, e, s) in enumerate(self.filas) if c.isChecked()]


class PersonalView(QWidget):
    titulo = "Empleados y usuarios"

    def __init__(self, ctx):
        super().__init__()
        self.setObjectName("pagina")
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.addWidget(etiqueta("Empleados y usuarios", "titulo"))
        fila = QHBoxLayout()
        self.b_nuevo = QPushButton("Nuevo empleado")
        self.b_nuevo.setProperty("rol", "primario")
        self.b_pin = QPushButton("Asignar / cambiar PIN")
        self.b_horario = QPushButton("Horario…")
        self.b_baja = QPushButton("Dar de baja")
        self.b_baja.setProperty("rol", "peligro")
        for b in (self.b_nuevo, self.b_pin, self.b_horario):
            fila.addWidget(b)
        fila.addStretch(1)
        fila.addWidget(self.b_baja)
        lay.addLayout(fila)
        self.tabla = crear_tabla(["Empleado", "Puesto", "Usuario", "PIN", "Horario", "Estado"])
        lay.addWidget(self.tabla, 1)
        self.por_id: dict[int, dict] = {}
        self.b_nuevo.clicked.connect(self.nuevo)
        self.b_pin.clicked.connect(self.cambiar_pin)
        self.b_horario.clicked.connect(self.horario)
        self.b_baja.clicked.connect(self.baja)

    def al_mostrar(self):
        ok, emps = seguro(self, empleados.listar_empleados, self.ctx.conn, False)
        ok, usrs = seguro(self, usuarios.listar_usuarios, self.ctx.conn, self.ctx.admin)
        por_emp = {u["empleado_id"]: u for u in usrs or [] if u["empleado_id"]}
        self.por_id = {}
        filas = []
        for e in emps or []:
            u = por_emp.get(e["id"])
            self.por_id[e["id"]] = {"empleado": e, "usuario": u}
            filas.append((e["id"], [f"{e['nombre']} {e['apellidos']}", e["puesto"] or "", u["usuario"] if u else "—",
                                    "Sí" if u and u["tiene_pin"] else "No",
                                    self._resumen_horario(e["id"]) if e["activo"] else "", "Activo" if e["activo"] else "Baja"]))
        poblar(self.tabla, filas)

    def _resumen_horario(self, eid: int) -> str:
        dias = sorted(t["dia_semana"] for t in empleados.turnos_vigentes(self.ctx.conn, eid))
        return ", ".join(DIAS[d - 1][:3] for d in dias) if dias else "Sin horario"

    def nuevo(self):
        dlg = EmpleadoDialog(self)
        if not dlg.exec():
            return
        ok, r = seguro(self, usuarios.alta_empleado_con_acceso, self.ctx.conn, self.ctx.admin, dlg.nombre.text(),
                       dlg.apellidos.text(), dlg.ingreso.date().toPython(), dlg.pin.text(), dlg.telefono.text(), dlg.puesto.text())
        if ok:
            QMessageBox.information(self, "Empleado creado", f"Listo. Su PIN es {dlg.pin.text()}.\n"
                                    "Pídele que lo cambie cuando quiera.")
            self.al_mostrar()

    def cambiar_pin(self):
        eid = id_seleccionado(self.tabla)
        u = self.por_id.get(eid, {}).get("usuario") if eid else None
        if not u:
            QMessageBox.information(self, "Oceánica", "Selecciona un empleado con usuario.")
            return
        pin, ok = QInputDialog.getText(self, "PIN nuevo", "PIN de 4 a 6 dígitos:", QLineEdit.Password, pin_aleatorio())
        if ok and seguro(self, usuarios.asignar_pin, self.ctx.conn, self.ctx.admin, u["id"], pin)[0]:
            QMessageBox.information(self, "Oceánica", "PIN actualizado (y la cuenta quedó desbloqueada).")
            self.al_mostrar()

    def horario(self):
        eid = id_seleccionado(self.tabla)
        if eid is None or not self.por_id[eid]["empleado"]["activo"]:
            QMessageBox.information(self, "Oceánica", "Selecciona un empleado activo.")
            return
        e = self.por_id[eid]["empleado"]
        actuales = {t["dia_semana"]: (t["hora_entrada"].strftime("%H:%M"), t["hora_salida"].strftime("%H:%M"))
                    for t in empleados.turnos_vigentes(self.ctx.conn, eid)}
        dlg = HorarioDialog(self, f"{e['nombre']} {e['apellidos']}", actuales)
        if dlg.exec() and seguro(self, empleados.definir_turnos, self.ctx.conn, self.ctx.admin, eid, dlg.turnos(), date.today())[0]:
            QMessageBox.information(self, "Oceánica", "Horario guardado.")
            self.al_mostrar()

    def baja(self):
        eid = id_seleccionado(self.tabla)
        if eid is None or not self.por_id[eid]["empleado"]["activo"]:
            return
        e = self.por_id[eid]["empleado"]
        if QMessageBox.question(self, "Dar de baja", f"¿Dar de baja a {e['nombre']} {e['apellidos']}?\n"
                                "Se conserva su historial y ya no podrá entrar con su PIN.") != QMessageBox.Yes:
            return
        if seguro(self, empleados.dar_de_baja, self.ctx.conn, self.ctx.admin, eid, date.today())[0]:
            self.al_mostrar()
