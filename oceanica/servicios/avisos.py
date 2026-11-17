"""Aviso al cliente de que su ropa está lista, por WhatsApp.

El sistema NO envía el mensaje: arma un enlace `wa.me` con el texto ya escrito y el empleado lo manda
desde WhatsApp (Web o de escritorio) en la computadora del mostrador. Por eso lo que se guarda es que
el aviso se preparó y quién lo hizo, no que el cliente lo recibió.
"""
from __future__ import annotations

import re
from decimal import Decimal
from urllib.parse import quote

from ..db import transaccion
from .comunes import ErrorNegocio, auditar, config_valor, requerir_rol


def telefono_whatsapp(telefono) -> str:
    """Teléfono mexicano en el formato que pide wa.me: 52 + 10 dígitos, sin signos.
    Acepta '55 1234 5678', '+52 55 1234 5678' y el formato viejo '+52 1 55 1234 5678'."""
    digitos = re.sub(r"\D", "", telefono or "")
    if len(digitos) == 13 and digitos.startswith("521"):
        digitos = digitos[3:]
    elif len(digitos) == 12 and digitos.startswith("52"):
        digitos = digitos[2:]
    if len(digitos) != 10:
        raise ErrorNegocio("El teléfono del cliente no tiene 10 dígitos. Corríjalo en «Clientes» para poder avisarle.")
    return "52" + digitos


def _dinero(valor) -> str:
    return f"${Decimal(valor):,.2f}"


def aviso_orden_lista(conn, orden_id: int) -> dict:
    """Mensaje y enlace para avisar que la orden está lista. No cambia nada en la base.
    Devuelve {'telefono', 'mensaje', 'enlace', 'avisado_en'}."""
    with transaccion(conn) as cur:
        cur.execute(
            "SELECT o.folio, o.estado, o.tipo_entrega, o.avisado_en, s.saldo, c.nombre, c.telefono "
            "FROM ordenes o JOIN v_saldo_ordenes s ON s.orden_id = o.id LEFT JOIN clientes c ON c.id = o.cliente_id "
            "WHERE o.id = %s", (orden_id,))
        o = cur.fetchone()
        if not o:
            raise ErrorNegocio("Orden no encontrada.")
        negocio = config_valor(cur, "negocio_nombre", "") or "la lavandería"
    if o["estado"] != "lista":
        raise ErrorNegocio("Solo se avisa cuando la orden está lista para entregar.")
    if not o["telefono"]:
        raise ErrorNegocio("La orden no tiene cliente con teléfono: no hay a quién avisar.")
    telefono = telefono_whatsapp(o["telefono"])
    saldo = Decimal(o["saldo"])
    partes = [f"Hola {o['nombre']}, le saluda {negocio}.", f"Su ropa de la orden {o['folio']} ya está lista."]
    partes.append(f"Saldo por pagar: {_dinero(saldo)}." if saldo > 0 else "Ya está pagada.")
    partes.append("La llevaremos a su domicilio." if o["tipo_entrega"] == "domicilio"
                  else "Puede pasar a recogerla con su ticket.")
    partes.append("¡Gracias por su preferencia!")
    mensaje = " ".join(partes)
    return {"telefono": telefono, "mensaje": mensaje, "enlace": f"https://wa.me/{telefono}?text={quote(mensaje)}",
            "avisado_en": o["avisado_en"]}


def registrar_aviso(conn, sesion, orden_id: int) -> None:
    """Anota que se preparó el aviso (quién y cuándo). Avisar de nuevo actualiza la fecha."""
    requerir_rol(sesion, "administrador", "empleado")
    with transaccion(conn) as cur:
        cur.execute("SELECT folio, estado FROM ordenes WHERE id = %s FOR UPDATE", (orden_id,))
        o = cur.fetchone()
        if not o:
            raise ErrorNegocio("Orden no encontrada.")
        if o["estado"] != "lista":
            raise ErrorNegocio("Solo se avisa cuando la orden está lista para entregar.")
        cur.execute("UPDATE ordenes SET avisado_en = NOW(), avisado_por = %s WHERE id = %s", (sesion["id"], orden_id))
        auditar(cur, sesion, "aviso_orden_lista", "ordenes", orden_id, o["folio"])
