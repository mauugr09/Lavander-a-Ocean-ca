"""Caja: apertura, movimientos, corte y cierre."""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QInputDialog, QLineEdit, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from ..servicios import caja, tickets
from .dialogos import TicketDialog
from .util import a_decimal, crear_tabla, dinero, etiqueta, fecha_hora, poblar, seguro, tarjeta

TIPOS = {"gasto": "Gasto", "ingreso": "Ingreso", "retiro": "Retiro (solo administrador)"}


class CajaView(QWidget):
    titulo = "Caja"

    def __init__(self, ctx):
        super().__init__()
        self.setObjectName("pagina")
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        lay.addWidget(etiqueta("Caja", "titulo"))

        # --- caja cerrada
        self.p_cerrada = tarjeta()
        pc = QVBoxLayout(self.p_cerrada)
        pc.setContentsMargins(16, 16, 16, 16)
        pc.addWidget(etiqueta("No hay caja abierta", "subtitulo"))
        pc.addWidget(etiqueta("Cuenta el efectivo del cajón y captúralo como fondo inicial para poder cobrar.", "suave", True))
        fila = QHBoxLayout()
        self.fondo = QLineEdit("0.00")
        self.fondo.setMaximumWidth(160)
        self.b_abrir = QPushButton("Abrir caja")
        self.b_abrir.setProperty("rol", "primario")
        fila.addWidget(etiqueta("Fondo inicial $"))
        fila.addWidget(self.fondo)
        fila.addWidget(self.b_abrir)
        fila.addStretch(1)
        pc.addLayout(fila)
        lay.addWidget(self.p_cerrada)

        # --- caja abierta
        self.p_abierta = QWidget()
        pa = QVBoxLayout(self.p_abierta)
        pa.setContentsMargins(0, 0, 0, 0)
        self.lb_estado = etiqueta("", "subtitulo")
        pa.addWidget(self.lb_estado)
        self.tabla_res = crear_tabla(["Concepto", "Monto"], derecha=(1,))
        pa.addWidget(self.tabla_res)
        pa.addWidget(etiqueta("Movimientos del corte", "subtitulo"))
        self.tabla_mov = crear_tabla(["Hora", "Tipo", "Concepto", "Monto", "Quién"], derecha=(3,), estirar=2)
        pa.addWidget(self.tabla_mov, 1)
        fb = QHBoxLayout()
        self.b_mov = QPushButton("Registrar gasto / ingreso / retiro")
        self.b_cerrar = QPushButton("Cerrar caja")
        self.b_cerrar.setProperty("rol", "primario")
        fb.addWidget(self.b_mov)
        fb.addStretch(1)
        fb.addWidget(self.b_cerrar)
        pa.addLayout(fb)
        lay.addWidget(self.p_abierta, 1)

        self.b_abrir.clicked.connect(self.abrir)
        self.fondo.returnPressed.connect(self.abrir)
        self.b_mov.clicked.connect(self.movimiento)
        self.b_cerrar.clicked.connect(self.cerrar)

    def al_mostrar(self):
        ok, corte = seguro(self, caja.corte_abierto, self.ctx.conn)
        self.p_cerrada.setVisible(not corte)
        self.p_abierta.setVisible(bool(corte))
        if not corte:
            self.fondo.setFocus()
            return
        r = caja.resumen_corte(self.ctx.conn, corte["id"])
        self.lb_estado.setText(f"Caja abierta desde {fecha_hora(corte['abierta_en'])}")
        filas = [("fondo", ["Fondo inicial", dinero(corte["fondo_inicial"])])]
        filas += [(f"m{i}", [f"Cobrado en {m['metodo'].lower()}", dinero(m["total"])]) for i, m in enumerate(r["por_metodo"])]
        filas += [("i", ["Ingresos", dinero(r["ingresos"])]), ("g", ["Gastos", "-" + dinero(r["gastos"])]),
                  ("r", ["Retiros", "-" + dinero(r["retiros"])])]
        if self.ctx.es_admin:
            filas.append(("e", ["Efectivo esperado en caja", dinero(r["efectivo_esperado"])]))
        pend = r["transferencias_pendientes"]
        if pend["cantidad"]:
            filas.append(("p", [f"Transferencias por confirmar ({pend['cantidad']})", dinero(pend["total"])]))
        poblar(self.tabla_res, filas)
        self.tabla_res.setFixedHeight(40 + 34 * len(filas))
        movs = caja.movimientos_corte(self.ctx.conn, corte["id"])
        poblar(self.tabla_mov, [(m["id"], [m["creado_en"].strftime("%H:%M"), TIPOS[m["tipo"]].split(" (")[0], m["concepto"],
                                          dinero(m["monto"]), m["usuario"]]) for m in movs])

    def abrir(self):
        fondo = a_decimal(self.fondo.text())
        if fondo is None or fondo < 0:
            QMessageBox.warning(self, "Oceánica", "Escribe un fondo inicial válido (puede ser 0).")
            return
        sesion = self.ctx.identificar(self, sensible=True, titulo="Confirma con tu PIN para abrir la caja")
        if not sesion:
            return
        ok, _ = seguro(self, caja.abrir_corte, self.ctx.conn, sesion, fondo)
        if ok:
            self.al_mostrar()

    def movimiento(self):
        opciones = [t for t in TIPOS if t != "retiro" or self.ctx.es_admin]
        etiquetas = [TIPOS[t].split(" (")[0] for t in opciones]
        elegido, ok = QInputDialog.getItem(self, "Movimiento de caja", "Tipo:", etiquetas, 0, False)
        if not ok:
            return
        tipo = opciones[etiquetas.index(elegido)]
        concepto, ok = QInputDialog.getText(self, "Movimiento de caja", "Concepto (por ejemplo: compra de jabón):")
        if not ok or not concepto.strip():
            return
        monto, ok = QInputDialog.getText(self, "Movimiento de caja", "Monto $:")
        if not ok:
            return
        m = a_decimal(monto)
        if m is None or m <= 0:
            QMessageBox.warning(self, "Oceánica", "Escribe un monto mayor que cero.")
            return
        sesion = self.ctx.identificar(self, sensible=True, titulo="Confirma con tu PIN")
        if not sesion:
            return
        ok, _ = seguro(self, caja.registrar_movimiento, self.ctx.conn, sesion, tipo, concepto, m)
        if ok:
            self.al_mostrar()

    def cerrar(self):
        texto, ok = QInputDialog.getText(self, "Cerrar caja", "Cuenta el efectivo del cajón y escribe cuánto hay $:")
        if not ok:
            return
        contado = a_decimal(texto)
        if contado is None or contado < 0:
            QMessageBox.warning(self, "Oceánica", "Escribe un monto válido.")
            return
        sesion = self.ctx.identificar(self, sensible=True, titulo="Confirma con tu PIN para cerrar la caja")
        if not sesion:
            return
        obs = None
        while True:
            ok, r = seguro(self, caja.cerrar_corte, self.ctx.conn, sesion, contado, obs) if obs is not None else \
                self._intentar_cierre(sesion, contado)
            if ok or r != "diferencia":
                break
            obs, ok2 = QInputDialog.getText(self, "Hay diferencia", "El efectivo no coincide con lo esperado.\n"
                                            "Explica la diferencia para poder cerrar:")
            if not ok2 or not obs.strip():
                return
        if ok and isinstance(r, dict):
            corte_id = r["corte"]["id"]
            self.al_mostrar()
            TicketDialog(self, tickets.ticket_corte_texto(self.ctx.conn, corte_id), f"corte-{corte_id}.pdf",
                         "Corte de caja").exec()

    def _intentar_cierre(self, sesion, contado):
        """Primer intento sin observación: si hay diferencia pide la explicación en vez de solo marcar error."""
        from ..servicios.comunes import ErrorNegocio
        try:
            return True, caja.cerrar_corte(self.ctx.conn, sesion, contado, None)
        except ErrorNegocio as e:
            if str(e).startswith("Hay una diferencia"):
                return False, "diferencia"
            QMessageBox.warning(self, "Oceánica", str(e))
            return False, None
