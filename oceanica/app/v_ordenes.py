"""Órdenes: búsqueda, seguimiento, cobro del saldo, entrega y cancelación."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from html import escape

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLineEdit, QMessageBox, QPushButton, QTextBrowser,
                               QVBoxLayout, QWidget)

from ..servicios import avisos, caja, configuracion, facturacion, ordenes, tickets
from . import tema
from .cobro import CobroDialog
from .dialogos import TicketDialog
from .iconos import en_buscador, poner
from .util import (ESTADOS, cantidad_txt, crear_tabla, dinero, etiqueta, fecha_hora, id_seleccionado, poblar, seguro,
                   tarjeta)

SIGUIENTE = {"recibida": ("en_proceso", "Pasar a «En proceso»", "player-play"),
             "en_proceso": ("lista", "Marcar como «Lista»", "check")}
FILTROS = [("Pendientes de entregar", None), ("Todas", "todas"), ("Recibidas", "recibida"), ("En proceso", "en_proceso"),
           ("Listas", "lista"), ("Entregadas", "entregada"), ("Canceladas", "cancelada"), ("Por facturar", "por_facturar")]


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
        self.buscar.setPlaceholderText("Buscar por folio, nombre o teléfono")
        en_buscador(self.buscar)
        self.filtro = QComboBox()
        for texto, valor in FILTROS:
            self.filtro.addItem(texto, valor)
        fila.addWidget(self.buscar, 1)
        fila.addWidget(self.filtro)
        izq.addLayout(fila)
        self.tabla = crear_tabla(["Folio", "Cliente", "Estado", "Entrega", "Total", "Por pagar"], derecha=(4, 5), estirar=1)
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
        self.b_avanzar = poner(QPushButton("Pasar a «En proceso»"), "player-play")
        self.b_cobrar = poner(QPushButton("Cobrar lo pendiente"), "cash-banknote")
        f1.addWidget(self.b_avanzar)
        f1.addWidget(self.b_cobrar)
        dl.addLayout(f1)
        f2 = QHBoxLayout()
        self.b_entregar = poner(QPushButton("Entregar al cliente"), "package-export", "white", 24)
        self.b_entregar.setProperty("rol", "primario")
        self.b_ticket = poner(QPushButton("Ticket"), "printer")
        self.b_factura = poner(QPushButton("Factura"), "receipt")
        self.b_cancelar = QPushButton("Cancelar orden")
        self.b_cancelar.setProperty("rol", "peligro")
        f2.addWidget(self.b_entregar, 1)
        f2.addWidget(self.b_ticket)
        f2.addWidget(self.b_cancelar)
        dl.addLayout(f2)
        f3 = QHBoxLayout()
        self.b_avisar = QPushButton("Avisar por WhatsApp")
        self.b_etiquetas = poner(QPushButton("Etiquetas de bolsa"), "tag")
        f3.addWidget(self.b_avisar, 1)
        f3.addWidget(self.b_etiquetas)
        f3.addWidget(self.b_factura)
        dl.addLayout(f3)
        for b in (self.b_avanzar, self.b_cobrar, self.b_entregar, self.b_ticket, self.b_cancelar, self.b_avisar,
                  self.b_etiquetas):
            b.setMinimumHeight(52)
        self.b_entregar.setStyleSheet("font-size: 13pt;")
        self.buscar.setMinimumHeight(44)
        self.filtro.setMinimumHeight(44)
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
        self.b_factura.clicked.connect(self.factura)
        self.b_cancelar.clicked.connect(self.cancelar)
        self.b_avisar.clicked.connect(self.avisar)
        self.b_etiquetas.clicked.connect(self.etiquetas)
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
        if sel == "por_facturar":
            kw = {"por_facturar": True}
        else:
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
        self.lb_cuenta.setText(f"{len(filas)} orden(es)" + ("  ·  Rojo: entrega atrasada  ·  Naranja: lista, falta pagar" if filas else ""))
        if filas and self.tabla.currentRow() < 0:
            self.tabla.selectRow(0)
        self._mostrar_detalle()

    def _enter_en_busqueda(self):
        """Enter en la búsqueda (también el lector de código de barras, que escribe el folio y Enter): si es el folio
        exacto de una orden que no está en el filtro actual (por ejemplo, ya entregada), se busca en todas."""
        texto = self.buscar.text().strip().upper()
        if texto and not self._fila_de_folio(texto) and self.filtro.currentData() != "todas":
            self.filtro.setCurrentIndex(self.filtro.findData("todas"))   # recarga con el mismo texto
        fila = self._fila_de_folio(texto)
        if fila is None and self.tabla.rowCount():
            fila = 0
        if fila is not None:
            self.tabla.selectRow(fila)
            self.tabla.setFocus()

    def _fila_de_folio(self, folio: str) -> int | None:
        for r in range(self.tabla.rowCount()):
            if self.tabla.item(r, 0) and self.tabla.item(r, 0).text().upper() == folio:
                return r
        return None

    # -------------------------------------------------------------- detalle
    def _mostrar_detalle(self):
        oid = id_seleccionado(self.tabla)
        self.orden = None
        if oid is None:
            self.detalle.setHtml("<p style='color:#5B6F86'>Seleccione una orden de la lista para ver su detalle.</p>")
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
        if o.get("tipo_entrega") == "domicilio":
            h.append(f"<p style='font-size:13pt; color:{tema.PRIMARIO}'><b>Servicio a domicilio</b> "
                     f"(cargo {dinero(o['cargo_domicilio'])})<br>{escape(o['direccion_entrega'] or '')}</p>")
        else:
            h.append("<p>Recoge en mostrador</p>")
        h.append(f"<p style='font-size:13pt'><b>Total {dinero(o['total'])}</b> · Pagado {dinero(o['pagado'])}</p>")
        h.append(f"<p style='font-size:15pt; color:{tema.ALERTA}'><b>Por pagar: {dinero(o['saldo'])}</b></p>" if o["saldo"] > 0
                 else f"<p style='font-size:15pt; color:{tema.OK}'><b>Pagado completo</b></p>")
        if o["por_confirmar"] > 0:
            h.append(f"<p style='color:{tema.ALERTA}'><b>Atención:</b> {dinero(o['por_confirmar'])} en transferencia por confirmar</p>")
        for p in o["pagos"]:
            marca = {"pendiente": " (por confirmar)", "rechazado": " (rechazado)"}.get(p["estado_confirmacion"], "")
            h.append(f"<small>{fecha_hora(p['pagado_en'])} · {p['tipo']} {dinero(p['monto'])} · "
                     f"{escape(p['metodo'])}{marca}</small><br>")
        if o.get("observaciones"):
            h.append(f"<p>Nota: {escape(o['observaciones'])}</p>")
        if o["estado"] == "lista":
            h.append(f"<p style='color:{tema.OK}'>Se le avisó por WhatsApp el {fecha_hora(o['avisado_en'])}</p>" if o.get("avisado_en")
                     else "<p>Todavía no se le avisa al cliente que está lista</p>")
        if o["facturada"]:
            h.append(f"<p style='color:{tema.OK}'>Facturada" + (f" · folio {escape(o['factura_folio'])}" if o["factura_folio"] else "")
                     + f" · {fecha_hora(o['facturada_en'])} ({escape(o['facturo'] or '')})</p>")
        elif o["requiere_factura"]:
            falta = facturacion.faltantes(cli)
            h.append(f"<p style='color:{tema.ALERTA}'>Pidió factura, falta emitirla"
                     + (f"<br><small>Faltan datos del cliente: {escape(', '.join(falta))}</small>" if falta else "") + "</p>")
        self.detalle.setHtml("".join(h))
        self._botones()

    def _botones(self):
        o = self.orden
        abierta = bool(o) and o["estado"] in ("recibida", "en_proceso", "lista")
        sig = SIGUIENTE.get(o["estado"]) if o else None
        self.b_avanzar.setVisible(sig is not None)
        if sig:
            self.b_avanzar.setText(sig[1])
            poner(self.b_avanzar, sig[2])
        self.b_cobrar.setEnabled(bool(o) and o["estado"] != "cancelada" and o["saldo"] > 0)
        self.b_entregar.setEnabled(abierta)
        self.b_cancelar.setEnabled(abierta)
        self.b_ticket.setEnabled(bool(o))
        self.b_etiquetas.setEnabled(abierta)
        self.b_avisar.setEnabled(bool(o) and o["estado"] == "lista" and bool(o["cliente"]) and bool(o["cliente"]["telefono"]))
        self.b_factura.setEnabled(bool(o) and (o["estado"] != "cancelada" or bool(o["facturada"])))

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
        dlg = CobroDialog(self.ctx, self, o["saldo"], f"Cobro pendiente de la orden {o['folio']}", permite_cero=False, texto_importe="Por pagar")
        if not dlg.exec() or not dlg.pago:
            return False
        sesion = self.ctx.identificar(self, sensible=True, titulo="Confirme con su PIN para cobrar")
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
                    entrega = self.ctx.identificar(self, sensible=True, titulo="¿Quién entrega? Confirme con su PIN")
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
            entrega = self.ctx.identificar(self, sensible=True, titulo="¿Quién entrega? Confirme con su PIN")
            if not entrega:
                return
            ok, _ = seguro(self, ordenes.cambiar_estado, self.ctx.conn, encargada, o["id"], "entregada",
                           f"Autorizó {encargada['usuario']}, entregó {entrega['usuario']} (transferencia por confirmar)")
            if ok:
                self._tras_cambio()
            return
        sesion = self.ctx.identificar(self, sensible=True, titulo="Confirme con su PIN para entregar")
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
            dlg = CobroDialog(self.ctx, self, o["pagado"], "Reembolso al cliente", permite_cero=False, texto_importe="Pagado",
                              reembolso=True)
            if not dlg.exec() or not dlg.pago:
                return
            reembolso = dlg.pago
        sesion = self.ctx.identificar(self, sensible=True, titulo="Confirme con su PIN para cancelar")
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

    def factura(self):
        """Empleado: anota que el cliente pidió (o ya no pide) factura. Encargada: además, que ya se emitió."""
        o = self.orden
        if not o:
            return
        if o["facturada"]:
            if not self.ctx.es_admin:
                QMessageBox.information(self, "Factura", f"{o['folio']} ya está facturada"
                                        + (f" (folio {o['factura_folio']})." if o["factura_folio"] else "."))
                return
            caja_ = QMessageBox(QMessageBox.Question, "Factura",
                                f"{o['folio']} está marcada como facturada"
                                + (f" (folio {o['factura_folio']})." if o["factura_folio"] else ".")
                                + "\n\nQuite la marca solo si hubo un error o si se canceló la factura en el SAT.", parent=self)
            b_quitar = caja_.addButton("Quitar marca de facturada", QMessageBox.DestructiveRole)
            caja_.addButton("Cancelar", QMessageBox.RejectRole)
            caja_.exec()
            if caja_.clickedButton() is not b_quitar:
                return
            motivo, okp = QInputDialog.getText(self, "Quitar marca de facturada", "Motivo (obligatorio):")
            if not okp or not motivo.strip():
                return
            ok, _ = seguro(self, facturacion.desmarcar_facturada, self.ctx.conn, self.ctx.admin, o["id"], motivo)
            if ok:
                self._tras_cambio()
            return

        caja_ = QMessageBox(QMessageBox.Question, "Factura", f"{o['folio']}: "
                            + ("el cliente pidió factura." if o["requiere_factura"] else "no se ha pedido factura."), parent=self)
        b_marcar = caja_.addButton("Ya se facturó", QMessageBox.AcceptRole) if self.ctx.es_admin else None
        b_pedir = None if o["requiere_factura"] else caja_.addButton("El cliente pide factura", QMessageBox.ActionRole)
        b_quitar = caja_.addButton("Ya no la pide", QMessageBox.ActionRole) if o["requiere_factura"] else None
        caja_.addButton("Cancelar", QMessageBox.RejectRole)
        caja_.exec()
        elegido = caja_.clickedButton()
        if elegido is None or elegido not in (b_marcar, b_pedir, b_quitar):
            return
        if elegido is b_marcar:
            folio, okp = QInputDialog.getText(self, "Factura emitida", "Folio o UUID de la factura (opcional):")
            if not okp:
                return
            ok, _ = seguro(self, facturacion.marcar_facturada, self.ctx.conn, self.ctx.admin, o["id"], folio)
        else:
            sesion = self.ctx.identificar(self, sensible=False)
            if not sesion:
                return
            ok, _ = seguro(self, facturacion.marcar_requiere_factura, self.ctx.conn, sesion, o["id"], elegido is b_pedir)
        if ok:
            self._tras_cambio()

    def avisar(self):
        """Abre WhatsApp con el mensaje ya escrito; el empleado lo envía. Aquí solo se anota que se avisó."""
        if not self.orden:
            return
        oid = self.orden["id"]
        ok, aviso = seguro(self, avisos.aviso_orden_lista, self.ctx.conn, oid)
        if not ok:
            return
        if aviso["avisado_en"] and QMessageBox.question(
                self, "Ya se le avisó", f"A este cliente ya se le avisó el {fecha_hora(aviso['avisado_en'])}.\n\n"
                "¿Avisarle otra vez?") != QMessageBox.Yes:
            return
        sesion = self.ctx.identificar(self, sensible=False)
        if not sesion:
            return
        if not QDesktopServices.openUrl(QUrl(aviso["enlace"])):
            QMessageBox.warning(self, "WhatsApp", "No se pudo abrir WhatsApp. Revise que haya internet y un navegador.")
            return
        if QMessageBox.question(self, "WhatsApp", "Se abrió WhatsApp con el mensaje escrito.\n\n"
                                "¿Ya lo envió? (Si no se envió, responda No para que no quede anotado.)") != QMessageBox.Yes:
            return
        if seguro(self, avisos.registrar_aviso, self.ctx.conn, sesion, oid)[0]:
            self._mostrar_detalle()

    def etiquetas(self):
        if not self.orden:
            return
        n, ok = QInputDialog.getInt(self, "Etiquetas de bolsa", "¿Cuántas bolsas o paquetes son?", 1, 1, 30)
        if not ok:
            return
        ok, texto = seguro(self, tickets.etiquetas_bolsa_texto, self.ctx.conn, self.orden["id"], n)
        if ok:
            TicketDialog(self, texto, f"{self.orden['folio']}-etiquetas.pdf", f"Etiquetas {self.orden['folio']}",
                         imprimir=lambda: tickets.imprimir_texto(texto, configuracion.obtener(self.ctx.conn, "impresora_ticket") or None)).exec()

    def ver_ticket(self):
        if self.orden:
            oid = self.orden["id"]
            TicketDialog(self, tickets.ticket_orden_texto(self.ctx.conn, oid), f"{self.orden['folio']}.pdf",
                         f"Ticket {self.orden['folio']}", imprimir=lambda: tickets.imprimir_ticket_orden(self.ctx.conn, oid),
                         logo=tickets.logo_activo(self.ctx.conn)).exec()
