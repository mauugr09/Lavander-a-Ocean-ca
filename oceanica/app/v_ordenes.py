"""Órdenes: búsqueda, seguimiento, cobro del saldo, entrega y cancelación."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLineEdit, QMessageBox, QPushButton, QTextBrowser,
                               QVBoxLayout, QWidget)

from ..servicios import caja, configuracion, ordenes, tickets
from . import tema
from .dialogos import CobroDialog, TicketDialog
from .util import (ESTADOS, cantidad_txt, crear_tabla, dinero, etiqueta, fecha_hora, id_seleccionado, poblar, seguro,
                   tarjeta)

SIGUIENTE = {"recibida": ("en_proceso", "Marcar en proceso"), "en_proceso": ("lista", "Marcar lista")}
FILTROS = [("Abiertas", None), ("Todas", "todas"), ("Recibidas", "recibida"), ("En proceso", "en_proceso"),
           ("Listas", "lista"), ("Entregadas", "entregada"), ("Canceladas", "cancelada")]


class OrdenesView(QWidget):
    titulo = "Órdenes"

    def __init__(self, ctx):
        super().__init__()
        self.setObjectName("pagina")
        self.ctx = ctx
        self.orden: dict | None = None
        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(16, 16, 16, 16)
        raiz.setSpacing(14)

        izq = QVBoxLayout()
        fila = QHBoxLayout()
        self.buscar = QLineEdit()
        self.buscar.setPlaceholderText("Folio, cliente o teléfono  (F3)")
        self.filtro = QComboBox()
        for texto, valor in FILTROS:
            self.filtro.addItem(texto, valor)
        fila.addWidget(self.buscar, 1)
        fila.addWidget(self.filtro)
        izq.addLayout(fila)
        self.tabla = crear_tabla(["Folio", "Cliente", "Estado", "Entrega", "Total", "Saldo"], derecha=(4, 5), estirar=1)
        izq.addWidget(self.tabla, 1)
        self.lb_cuenta = etiqueta("", "suave")
        izq.addWidget(self.lb_cuenta)
        raiz.addLayout(izq, 6)

        der = tarjeta()
        dl = QVBoxLayout(der)
        dl.setContentsMargins(14, 14, 14, 14)
        self.detalle = QTextBrowser()
        self.detalle.setFrameShape(QTextBrowser.NoFrame)
        dl.addWidget(self.detalle, 1)
        f1 = QHBoxLayout()
        self.b_avanzar = QPushButton("Marcar en proceso")
        self.b_cobrar = QPushButton("Cobrar saldo (F6)")
        f1.addWidget(self.b_avanzar)
        f1.addWidget(self.b_cobrar)
        dl.addLayout(f1)
        f2 = QHBoxLayout()
        self.b_entregar = QPushButton("Entregar (F7)")
        self.b_entregar.setProperty("rol", "primario")
        self.b_ticket = QPushButton("Ticket")
        self.b_cancelar = QPushButton("Cancelar orden")
        self.b_cancelar.setProperty("rol", "peligro")
        f2.addWidget(self.b_entregar, 1)
        f2.addWidget(self.b_ticket)
        f2.addWidget(self.b_cancelar)
        dl.addLayout(f2)
        raiz.addWidget(der, 4)

        self.buscar.textChanged.connect(self.recargar)
        self.buscar.returnPressed.connect(self._enter_en_busqueda)
        self.filtro.currentIndexChanged.connect(self.recargar)
        self.tabla.itemSelectionChanged.connect(self._mostrar_detalle)
        self.tabla.itemActivated.connect(lambda *_: self.b_entregar.setFocus())
        self.b_avanzar.clicked.connect(self.avanzar)
        self.b_cobrar.clicked.connect(self.cobrar)
        self.b_entregar.clicked.connect(self.entregar)
        self.b_ticket.clicked.connect(self.ver_ticket)
        self.b_cancelar.clicked.connect(self.cancelar)
        QShortcut(QKeySequence("F3"), self, activated=self.buscar.setFocus)
        QShortcut(QKeySequence("F6"), self, activated=self.cobrar)
        QShortcut(QKeySequence("F7"), self, activated=self.entregar)
        self._botones()

    # ---------------------------------------------------------------- lista
    def al_mostrar(self):
        self.recargar()
        self.buscar.setFocus()

    def abrir(self, folio: str):
        """Muestra la orden con ese folio (la usa el mostrador al terminar de capturar)."""
        self.filtro.setCurrentIndex(1)
        self.buscar.setText(folio)

    def recargar(self):
        sel = self.filtro.currentData()
        kw = {"solo_abiertas": True} if sel is None else ({} if sel == "todas" else {"estados": [sel]})
        ok, filas = seguro(self, ordenes.listar_ordenes, self.ctx.conn, texto_busqueda=self.buscar.text() or None, **kw)
        filas = filas or []
        ahora = datetime.now()

        def color(oid):
            f = idx[oid]
            if f["estado"] in ("recibida", "en_proceso", "lista") and f["fecha_promesa"] and f["fecha_promesa"] < ahora:
                return QColor(tema.ERROR)
            if f["estado"] == "lista" and f["saldo"] > 0:
                return QColor(tema.ALERTA)
            return None

        idx = {f["id"]: f for f in filas}
        poblar(self.tabla, [(f["id"], [f["folio"], f["cliente"] or "Mostrador", ESTADOS[f["estado"]],
                                       fecha_hora(f["fecha_promesa"]), dinero(f["total"]),
                                       dinero(f["saldo"]) if f["saldo"] > 0 else "—"]) for f in filas], color)
        self.lb_cuenta.setText(f"{len(filas)} orden(es)" + ("  ·  rojo = entrega vencida, naranja = lista con saldo" if filas else ""))
        if filas and self.tabla.currentRow() < 0:
            self.tabla.selectRow(0)
        self._mostrar_detalle()

    def _enter_en_busqueda(self):
        if self.tabla.rowCount():
            self.tabla.selectRow(0)
            self.tabla.setFocus()

    # -------------------------------------------------------------- detalle
    def _mostrar_detalle(self):
        oid = id_seleccionado(self.tabla)
        self.orden = None
        if oid is None:
            self.detalle.setHtml("<p style='color:#5B6F86'>Selecciona una orden para ver su detalle.</p>")
            return self._botones()
        ok, o = seguro(self, ordenes.obtener_orden, self.ctx.conn, oid)
        if not ok:
            return self._botones()
        self.orden = o
        cli = o["cliente"]
        nombre = " ".join(filter(None, [cli["nombre"], cli["apellidos"]])) if cli else "Mostrador"
        h = [f"<h2 style='color:{tema.PRIMARIO}'>{escape(o['folio'])} · {ESTADOS[o['estado']]}</h2>",
             f"<p><b>{escape(nombre)}</b>" + (f" · {escape(cli['telefono'])}" if cli and cli["telefono"] else "") + "<br>"
             f"Recibida {fecha_hora(o['fecha_recepcion'])} · Entrega {fecha_hora(o['fecha_promesa'])}<br>"
             f"Atendió: {escape(o['recibio'])}</p>", "<table width='100%' cellspacing='0' cellpadding='3'>"]
        for d in o["detalle"]:
            h.append(f"<tr><td>{escape(d['servicio'])}</td><td align='right'>{cantidad_txt(d['cantidad'], d['unidad'])}</td>"
                     f"<td align='right'>{dinero(d['importe'])}</td></tr>")
        h.append("</table><hr>")
        if Decimal(o["descuento"]) > 0:
            h.append(f"<p>Descuento: -{dinero(o['descuento'])}</p>")
        h.append(f"<p><b>Total {dinero(o['total'])}</b> · Pagado {dinero(o['pagado'])} · "
                 f"<b style='color:{tema.ALERTA if o['saldo'] > 0 else tema.OK}'>Saldo {dinero(o['saldo'])}</b></p>")
        if o["por_confirmar"] > 0:
            h.append(f"<p style='color:{tema.ALERTA}'>⚠ {dinero(o['por_confirmar'])} en transferencia por confirmar</p>")
        for p in o["pagos"]:
            marca = {"pendiente": " (por confirmar)", "rechazado": " (rechazado)"}.get(p["estado_confirmacion"], "")
            h.append(f"<small>{fecha_hora(p['pagado_en'])} · {p['tipo']} {dinero(p['monto'])} · "
                     f"{escape(p['metodo'])}{marca}</small><br>")
        if o.get("observaciones"):
            h.append(f"<p>Nota: {escape(o['observaciones'])}</p>")
        self.detalle.setHtml("".join(h))
        self._botones()

    def _botones(self):
        o = self.orden
        abierta = bool(o) and o["estado"] in ("recibida", "en_proceso", "lista")
        sig = SIGUIENTE.get(o["estado"]) if o else None
        self.b_avanzar.setVisible(sig is not None)
        if sig:
            self.b_avanzar.setText(sig[1])
        self.b_cobrar.setEnabled(bool(o) and o["estado"] != "cancelada" and o["saldo"] > 0)
        self.b_entregar.setEnabled(abierta)
        self.b_cancelar.setEnabled(abierta)
        self.b_ticket.setEnabled(bool(o))

    # ------------------------------------------------------------- acciones
    def _tras_cambio(self):
        self.recargar()

    def avanzar(self):
        if not self.orden or self.orden["estado"] not in SIGUIENTE:
            return
        sesion = self.ctx.identificar(self, sensible=False)
        if not sesion:
            return
        ok, _ = seguro(self, ordenes.cambiar_estado, self.ctx.conn, sesion, self.orden["id"], SIGUIENTE[self.orden["estado"]][0])
        if ok:
            self._tras_cambio()

    def cobrar(self) -> bool:
        o = self.orden
        if not o or o["saldo"] <= 0 or o["estado"] == "cancelada":
            return False
        dlg = CobroDialog(self.ctx, self, o["saldo"], f"Cobrar saldo de {o['folio']}", permite_cero=False, texto_importe="Saldo")
        if not dlg.exec() or not dlg.pago:
            return False
        sesion = self.ctx.identificar(self, sensible=True, titulo="Confirma con tu PIN para cobrar")
        if not sesion:
            return False
        p = dlg.pago
        ok, _ = seguro(self, caja.registrar_pago, self.ctx.conn, sesion, o["id"], p["metodo_pago_id"], p["monto"], "pago", p["referencia"])
        if ok:
            self._tras_cambio()
        return ok

    def entregar(self):
        o = self.orden
        if not o or o["estado"] not in ("recibida", "en_proceso", "lista"):
            return
        forzar, nota = False, None
        if o["saldo"] > 0:
            if self.ctx.es_admin:
                caja_ = QMessageBox(QMessageBox.Question, "Saldo pendiente",
                                    f"{o['folio']} tiene un saldo de {dinero(o['saldo'])}.", parent=self)
                b_cobrar = caja_.addButton("Cobrar ahora", QMessageBox.AcceptRole)
                b_forzar = caja_.addButton("Entregar sin cobrar", QMessageBox.DestructiveRole)
                caja_.addButton("Cancelar", QMessageBox.RejectRole)
                caja_.exec()
                if caja_.clickedButton() is b_cobrar:
                    if not self.cobrar():
                        return
                elif caja_.clickedButton() is b_forzar:
                    nota, okp = QInputDialog.getText(self, "Entrega sin cobrar", "Motivo (obligatorio):")
                    if not okp or not nota.strip():
                        return
                    forzar = True
                else:
                    return
            else:
                caja_ = QMessageBox(QMessageBox.Question, "Saldo pendiente",
                                    f"{o['folio']} tiene un saldo de {dinero(o['saldo'])}.", parent=self)
                b_cobrar = caja_.addButton("Cobrar ahora", QMessageBox.AcceptRole)
                b_auth = caja_.addButton("Pedir autorización de la encargada", QMessageBox.ActionRole)
                caja_.addButton("Cancelar", QMessageBox.RejectRole)
                caja_.exec()
                if caja_.clickedButton() is b_cobrar:
                    if not self.cobrar():
                        return
                elif caja_.clickedButton() is b_auth:
                    encargada = self.ctx.autorizar_admin(self, f"Autoriza la entrega de {o['folio']} con saldo de {dinero(o['saldo'])}")
                    if not encargada:
                        return
                    nota, okp = QInputDialog.getText(self, "Entrega sin cobrar", "Motivo (obligatorio):")
                    if not okp or not nota.strip():
                        return
                    entrega = self.ctx.identificar(self, sensible=True, titulo="¿Quién entrega? Confirma con tu PIN")
                    if not entrega:
                        return
                    nota = f"Autorizó {encargada['usuario']}, entregó {entrega['usuario']}: {nota.strip()}"
                    ok, _ = seguro(self, ordenes.cambiar_estado, self.ctx.conn, encargada, o["id"], "entregada", nota, True)
                    if ok:
                        self._tras_cambio()
                    return
                else:
                    return
        o = self.orden  # tras cobrar, la orden ya cambió (p. ej. quedó pagada con una transferencia)
        if not o or o["estado"] not in ("recibida", "en_proceso", "lista"):
            return
        if o.get("por_confirmar", 0) > 0 and not self.ctx.es_admin and \
                configuracion.obtener(self.ctx.conn, "entrega_transferencia_pendiente", "todos") == "admin":
            if QMessageBox.question(self, "Transferencia por confirmar",
                                    f"{o['folio']} tiene {dinero(o['por_confirmar'])} en transferencia sin confirmar en el banco.\n\n"
                                    "Para entregar necesitas la autorización de la encargada. ¿Pedirla ahora?") != QMessageBox.Yes:
                return
            encargada = self.ctx.autorizar_admin(self, f"Autoriza entregar {o['folio']} con transferencia por confirmar")
            if not encargada:
                return
            entrega = self.ctx.identificar(self, sensible=True, titulo="¿Quién entrega? Confirma con tu PIN")
            if not entrega:
                return
            ok, _ = seguro(self, ordenes.cambiar_estado, self.ctx.conn, encargada, o["id"], "entregada",
                           f"Autorizó {encargada['usuario']}, entregó {entrega['usuario']} (transferencia por confirmar)")
            if ok:
                self._tras_cambio()
            return
        sesion = self.ctx.identificar(self, sensible=True, titulo="Confirma con tu PIN para entregar")
        if not sesion:
            return
        ok, _ = seguro(self, ordenes.cambiar_estado, self.ctx.conn, sesion, o["id"], "entregada", nota, forzar)
        if ok:
            self._tras_cambio()

    def cancelar(self):
        o = self.orden
        if not o:
            return
        motivo, okp = QInputDialog.getText(self, "Cancelar orden", f"Motivo para cancelar {o['folio']}:")
        if not okp or not motivo.strip():
            return
        reembolso = None
        if o["pagado"] != 0:
            if not self.ctx.es_admin:
                QMessageBox.warning(self, "Oceánica", f"La orden tiene {dinero(o['pagado'])} cobrados. "
                                    "Solo el administrador puede reembolsar y cancelar.")
                return
            dlg = CobroDialog(self.ctx, self, o["pagado"], "Reembolso al cliente", permite_cero=False, texto_importe="Pagado")
            if not dlg.exec() or not dlg.pago:
                return
            reembolso = dlg.pago
        sesion = self.ctx.identificar(self, sensible=True, titulo="Confirma con tu PIN para cancelar")
        if not sesion:
            return
        if reembolso:
            ok, _ = seguro(self, caja.registrar_pago, self.ctx.conn, sesion, o["id"], reembolso["metodo_pago_id"],
                           reembolso["monto"], "reembolso", reembolso["referencia"])
            if not ok:
                return
        ok, _ = seguro(self, ordenes.cancelar_orden, self.ctx.conn, sesion, o["id"], motivo)
        if ok:
            self._tras_cambio()

    def ver_ticket(self):
        if self.orden:
            oid = self.orden["id"]
            TicketDialog(self, tickets.ticket_orden_texto(self.ctx.conn, oid), f"{self.orden['folio']}.pdf",
                         f"Ticket {self.orden['folio']}", imprimir=lambda: tickets.imprimir_ticket_orden(self.ctx.conn, oid)).exec()
