"""Asistencia: llegada y salida con PIN, y consulta del día."""
from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import (QComboBox, QDateEdit, QDialog, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox,
                               QPushButton, QTimeEdit, QVBoxLayout, QWidget)

from ..servicios import empleados
from .dialogos import _botones
from .util import a_decimal, crear_tabla, etiqueta, hora, id_seleccionado, poblar, seguro

ESTADO = {"presente": "Presente", "retardo": "Retardo", "falta": "Falta", "justificada": "Justificada", "descanso": "Descanso"}


ACCIONES = [("Autorizar horas extra", "extra"), ("Marcar falta", "falta"), ("Falta justificada (no se paga)", "justificada"),
            ("Día de descanso", "descanso"), ("Corregir hora de entrada y salida", "corregir")]


class AjusteDialog(QDialog):
    """Ajustes que solo hace la encargada: horas extra, faltas y correcciones de horario."""

    def __init__(self, parent, emps: list[dict], empleado_id: int | None):
        super().__init__(parent)
        self.setWindowTitle("Ajustes de asistencia")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.empleado = QComboBox()
        for e in emps:
            self.empleado.addItem(f"{e['nombre']} {e['apellidos']}", e["id"])
        if empleado_id is not None:
            self.empleado.setCurrentIndex(max(0, self.empleado.findData(empleado_id)))
        self.fecha = QDateEdit(QDate.currentDate())
        self.fecha.setCalendarPopup(True)
        self.fecha.setDisplayFormat("dd/MM/yyyy")
        self.accion = QComboBox()
        for texto, clave in ACCIONES:
            self.accion.addItem(texto, clave)
        self.horas = QLineEdit()
        self.horas.setPlaceholderText("Ej. 1.5  (a $50 por hora)")
        self.entrada, self.salida = QTimeEdit(QTime(9, 0)), QTimeEdit(QTime(15, 0))
        for w in (self.entrada, self.salida):
            w.setDisplayFormat("HH:mm")
        self.motivo = QLineEdit()
        self.motivo.setPlaceholderText("Motivo (obligatorio)")
        self.filas = {}
        for clave, etiq, w in (("e", "Empleado", self.empleado), ("f", "Día", self.fecha), ("a", "Qué quieres hacer", self.accion),
                               ("h", "Horas extra", self.horas), ("en", "Entrada", self.entrada), ("sa", "Salida", self.salida),
                               ("m", "Motivo", self.motivo)):
            form.addRow(etiq, w)
            self.filas[clave] = (form.labelForField(w), w)
        lay.addLayout(form)
        bb = _botones(self, "Guardar")
        bb.accepted.connect(self._validar)
        lay.addWidget(bb)
        self.accion.currentIndexChanged.connect(self._ajustar)
        self._ajustar()

    def _ajustar(self):
        a = self.accion.currentData()
        visibles = {"h": a == "extra", "en": a == "corregir", "sa": a == "corregir"}
        for clave, v in visibles.items():
            for w in self.filas[clave]:
                w.setVisible(v)

    def _validar(self):
        if self.empleado.currentData() is None or not self.motivo.text().strip() and self.accion.currentData() != "descanso":
            QMessageBox.warning(self, "Oceánica", "Elige al empleado y escribe el motivo.")
            return
        if self.accion.currentData() == "extra" and a_decimal(self.horas.text()) is None:
            QMessageBox.warning(self, "Oceánica", "Escribe cuántas horas extra se autorizan.")
            return
        self.accept()


class AsistenciaView(QWidget):
    titulo = "Asistencia"

    def __init__(self, ctx):
        super().__init__()
        self.setObjectName("pagina")
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.addWidget(etiqueta("Asistencia de hoy", "titulo"))
        lay.addWidget(etiqueta("Cada empleado registra su llegada y su salida con su PIN. "
                               "La asistencia es la base del pago por día trabajado.", "suave", True))
        self.tabla = crear_tabla(["Empleado", "Estado", "Entrada", "Salida", "Retardo (min)"], derecha=(4,))
        lay.addWidget(self.tabla, 1)
        fila = QHBoxLayout()
        self.b_llegada = QPushButton("Registrar mi llegada")
        self.b_llegada.setProperty("rol", "primario")
        self.b_salida = QPushButton("Registrar mi salida")
        fila.addWidget(self.b_llegada)
        fila.addWidget(self.b_salida)
        self.b_ajustes = QPushButton("Ajustes de la encargada…")
        fila.addStretch(1)
        fila.addWidget(self.b_ajustes)
        lay.addLayout(fila)
        self.b_ajustes.clicked.connect(self.ajustes)
        self.b_llegada.clicked.connect(lambda: self._registrar(True))
        self.b_salida.clicked.connect(lambda: self._registrar(False))

    def al_mostrar(self):
        ok, emps = seguro(self, empleados.listar_empleados, self.ctx.conn)
        ok, asis = seguro(self, empleados.listar_asistencias, self.ctx.conn, date.today(), date.today())
        por_emp = {a["empleado_id"]: a for a in asis or []}
        filas = []
        for e in emps or []:
            a = por_emp.get(e["id"])
            filas.append((e["id"], [f"{e['nombre']} {e['apellidos']}", ESTADO[a["estado"]] if a else "Sin registro",
                                    hora(a["hora_entrada"]) if a else "", hora(a["hora_salida"]) if a else "",
                                    a["minutos_retardo"] if a and a["minutos_retardo"] else ""]))
        poblar(self.tabla, filas)

    def _registrar(self, llegada: bool):
        sesion = self.ctx.identificar(self, sensible=True,
                                      titulo="Registra tu llegada con tu PIN" if llegada else "Registra tu salida con tu PIN")
        if not sesion:
            return
        emp_id = sesion.get("empleado_id")
        if self.ctx.es_admin:  # el administrador registra a quien tenga seleccionado en la tabla
            emp_id = id_seleccionado(self.tabla)
        if not emp_id:
            QMessageBox.warning(self, "Oceánica", "Esta cuenta no está ligada a un empleado."
                                if not self.ctx.es_admin else "Selecciona al empleado en la tabla.")
            return
        fn = empleados.registrar_entrada if llegada else empleados.registrar_salida
        ok, r = seguro(self, fn, self.ctx.conn, sesion, emp_id)
        if ok:
            if llegada and r.get("minutos_retardo"):
                QMessageBox.information(self, "Llegada registrada", f"Llegada registrada con {r['minutos_retardo']} min de retardo.")
            self.al_mostrar()

    def ajustes(self):
        """Horas extra, faltas y correcciones: las autoriza la encargada con su usuario y contraseña."""
        ok, emps = seguro(self, empleados.listar_empleados, self.ctx.conn)
        if not ok:
            return
        dlg = AjusteDialog(self, emps, id_seleccionado(self.tabla))
        if not dlg.exec():
            return
        encargada = self.ctx.autorizar_admin(self, "Autoriza este ajuste de asistencia")
        if not encargada:
            return
        eid, dia, accion, motivo = dlg.empleado.currentData(), dlg.fecha.date().toPython(), dlg.accion.currentData(), dlg.motivo.text()
        if accion == "extra":
            fn, args = empleados.autorizar_horas_extra, (eid, dia, a_decimal(dlg.horas.text()), motivo)
        elif accion == "corregir":
            ent = datetime.combine(dia, dlg.entrada.time().toPython())
            sal = datetime.combine(dia, dlg.salida.time().toPython())
            fn, args = empleados.corregir_asistencia, (eid, dia, ent, sal, motivo)
        else:
            fn, args = empleados.marcar_estado, (eid, dia, accion, motivo or None)
        if seguro(self, fn, self.ctx.conn, encargada, *args)[0]:
            QMessageBox.information(self, "Oceánica", "Ajuste guardado.")
            self.al_mostrar()
