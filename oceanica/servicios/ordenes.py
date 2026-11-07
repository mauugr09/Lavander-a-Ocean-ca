"""Órdenes de lavado: recepción, seguimiento de estados, entrega y cancelación."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import mysql.connector

from ..db import siguiente_folio, transaccion
from .caja import pagado_confirmado_cur, pagado_neto_cur, pendiente_confirmar_cur, registrar_pago_cur
from .comunes import (CERO, ErrorNegocio, auditar, cantidad, config_si, config_valor, dinero, es_admin,
                      escapar_like, requerir_rol, texto)

ESTADOS = ("recibida", "en_proceso", "lista", "entregada", "cancelada")
_ORDEN_FLUJO = {"recibida": 0, "en_proceso": 1, "lista": 2, "entregada": 3}


def _crear(conn, sesion, items, cliente_id, fecha_promesa, descuento, observaciones, anticipo) -> int:
    if not items:
        raise ErrorNegocio("Agrega al menos un servicio a la orden.")
    observaciones = texto(observaciones, "observaciones", 300, False)
    descuento = dinero(descuento, "descuento")
    if descuento < 0:
        raise ErrorNegocio("El descuento no puede ser negativo.")
    with transaccion(conn) as cur:
        if cliente_id is not None:
            cur.execute("SELECT id FROM clientes WHERE id = %s AND activo = 1", (cliente_id,))
            if not cur.fetchone():
                raise ErrorNegocio("El cliente no existe o está inactivo.")

        lineas, subtotal = [], CERO
        for it in items:
            cur.execute("SELECT id, nombre, unidad, precio FROM servicios WHERE id = %s AND activo = 1",
                        (it.get("servicio_id"),))
            s = cur.fetchone()
            if not s:
                raise ErrorNegocio("Uno de los servicios no existe o está inactivo.")
            cant = cantidad(it.get("cantidad"), f"cantidad de {s['nombre']}")
            if s["unidad"] == "pieza" and cant != cant.to_integral_value():
                raise ErrorNegocio(f"'{s['nombre']}' se cobra por pieza: la cantidad debe ser entera.")
            precio = Decimal(s["precio"])
            importe = dinero(cant * precio)
            subtotal += importe
            lineas.append((s["id"], texto(it.get("descripcion"), "descripción", 120, False), cant, precio, importe))

        if descuento > subtotal:
            raise ErrorNegocio("El descuento no puede ser mayor que el subtotal.")
        if descuento > 0 and not es_admin(sesion):
            tope = Decimal(config_valor(cur, "descuento_max_pct_empleado", "10") or "0")
            if subtotal == 0 or descuento * 100 / subtotal > tope:
                raise ErrorNegocio(f"Un empleado puede dar hasta {tope}% de descuento. Pide autorización al administrador.")
        total = subtotal - descuento

        ahora = datetime.now()
        if fecha_promesa is None:
            fecha_promesa = ahora + timedelta(days=int(config_valor(cur, "dias_entrega_default", "2") or 2))
        elif fecha_promesa < ahora - timedelta(minutes=5):
            raise ErrorNegocio("La fecha promesa no puede estar en el pasado.")

        prefijo = config_valor(cur, "folio_prefijo", "OC") or "OC"
        folio = siguiente_folio(cur, prefijo)
        cur.execute(
            "INSERT INTO ordenes (folio, cliente_id, usuario_id, fecha_recepcion, fecha_promesa, subtotal, "
            "descuento, total, observaciones) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (folio, cliente_id, sesion["id"], ahora, fecha_promesa, subtotal, descuento, total, observaciones),
        )
        orden_id = cur.lastrowid
        for servicio_id, desc, cant, precio, importe in lineas:
            cur.execute(
                "INSERT INTO orden_detalle (orden_id, servicio_id, descripcion, cantidad, precio_unitario, importe) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (orden_id, servicio_id, desc, cant, precio, importe),
            )
        cur.execute(
            "INSERT INTO orden_historial_estado (orden_id, estado_anterior, estado_nuevo, usuario_id) "
            "VALUES (%s, NULL, 'recibida', %s)",
            (orden_id, sesion["id"]),
        )
        if anticipo:
            monto = dinero(anticipo.get("monto"), "anticipo")
            if monto > total:
                raise ErrorNegocio("El anticipo no puede ser mayor que el total de la orden.")
            registrar_pago_cur(cur, sesion, orden_id, anticipo.get("metodo_pago_id"), monto,
                               "anticipo", anticipo.get("referencia"))
        auditar(cur, sesion, "orden_creada", "ordenes", orden_id, f"{folio} total ${total}")
        return orden_id


def crear_orden(conn, sesion, items: list[dict], cliente_id: int | None = None,
                fecha_promesa: datetime | None = None, descuento=0, observaciones: str | None = None,
                anticipo: dict | None = None) -> int:
    """items: [{'servicio_id', 'cantidad', 'descripcion'(opcional)}].
    anticipo: {'metodo_pago_id', 'monto', 'referencia'(opcional)} (requiere caja abierta).
    Todo ocurre en una sola transacción: si el anticipo falla, no se crea la orden."""
    requerir_rol(sesion, "administrador", "empleado")
    for intento in range(3):
        try:
            return _crear(conn, sesion, items, cliente_id, fecha_promesa, descuento, observaciones, anticipo)
        except mysql.connector.IntegrityError as e:
            # Dos órdenes simultáneas pudieron calcular el mismo folio: se reintenta.
            if e.errno == 1062 and "folio" in str(e).lower() and intento < 2:
                continue
            raise
    raise ErrorNegocio("No se pudo generar el folio de la orden. Intenta de nuevo.")


def cambiar_estado(conn, sesion, orden_id: int, nuevo_estado: str, nota: str | None = None,
                   forzar_entrega: bool = False) -> None:
    requerir_rol(sesion, "administrador", "empleado")
    if nuevo_estado not in ("en_proceso", "lista", "entregada"):
        raise ErrorNegocio("Para cancelar usa cancelar_orden.")
    nota = texto(nota, "nota", 200, False)
    with transaccion(conn) as cur:
        cur.execute("SELECT id, folio, estado, total FROM ordenes WHERE id = %s FOR UPDATE", (orden_id,))
        o = cur.fetchone()
        if not o:
            raise ErrorNegocio("Orden no encontrada.")
        actual = o["estado"]
        if actual in ("entregada", "cancelada"):
            raise ErrorNegocio(f"La orden ya está {actual} y no puede cambiar de estado.")
        if nuevo_estado == actual:
            raise ErrorNegocio(f"La orden ya está en estado '{actual}'.")
        if _ORDEN_FLUJO[nuevo_estado] < _ORDEN_FLUJO[actual]:
            if not es_admin(sesion):
                raise ErrorNegocio("Solo el administrador puede regresar una orden a un estado anterior.")
            if not nota:
                raise ErrorNegocio("Anota el motivo para regresar la orden a un estado anterior.")
        if nuevo_estado == "entregada":
            saldo = Decimal(o["total"]) - pagado_neto_cur(cur, orden_id)
            if saldo > 0 and config_si(cur, "entrega_requiere_pago_total", True):
                if not (forzar_entrega and es_admin(sesion)):
                    raise ErrorNegocio(f"La orden tiene un saldo pendiente de ${saldo}. Cóbralo antes de entregar.")
                if not nota:
                    raise ErrorNegocio("Anota el motivo para entregar con saldo pendiente.")
            elif saldo <= 0:
                sin_confirmar = Decimal(o["total"]) - pagado_confirmado_cur(cur, orden_id)
                if sin_confirmar > 0:
                    quien = config_valor(cur, "entrega_transferencia_pendiente", "todos")
                    if quien == "no" or (quien == "admin" and not es_admin(sesion)):
                        raise ErrorNegocio(
                            f"${sin_confirmar} están en transferencias por confirmar. "
                            + ("Espera la confirmación del administrador." if quien == "no"
                               else "Solo el administrador puede entregar antes de confirmarlas."))
                    auditar(cur, sesion, "entrega_transferencia_pendiente", "ordenes", orden_id,
                            f"{o['folio']}: ${sin_confirmar} por confirmar")
        cur.execute(
            "UPDATE ordenes SET estado = %s, fecha_entrega = " + ("NOW()" if nuevo_estado == "entregada" else "NULL")
            + " WHERE id = %s",
            (nuevo_estado, orden_id),
        )
        cur.execute(
            "INSERT INTO orden_historial_estado (orden_id, estado_anterior, estado_nuevo, usuario_id, nota) "
            "VALUES (%s,%s,%s,%s,%s)",
            (orden_id, actual, nuevo_estado, sesion["id"], nota),
        )
        auditar(cur, sesion, "orden_estado", "ordenes", orden_id, f"{o['folio']}: {actual} -> {nuevo_estado}")


def cancelar_orden(conn, sesion, orden_id: int, motivo: str) -> None:
    requerir_rol(sesion, "administrador", "empleado")
    motivo = texto(motivo, "motivo", 200)
    with transaccion(conn) as cur:
        cur.execute("SELECT id, folio, estado FROM ordenes WHERE id = %s FOR UPDATE", (orden_id,))
        o = cur.fetchone()
        if not o:
            raise ErrorNegocio("Orden no encontrada.")
        if o["estado"] in ("entregada", "cancelada"):
            raise ErrorNegocio(f"La orden ya está {o['estado']}.")
        if o["estado"] != "recibida" and not es_admin(sesion):
            raise ErrorNegocio("Solo el administrador puede cancelar una orden que ya está en proceso.")
        pagado = pagado_neto_cur(cur, orden_id)
        if pagado != 0:
            raise ErrorNegocio(f"La orden tiene ${pagado} cobrados. Registra primero el reembolso.")
        cur.execute("UPDATE ordenes SET estado = 'cancelada' WHERE id = %s", (orden_id,))
        cur.execute(
            "INSERT INTO orden_historial_estado (orden_id, estado_anterior, estado_nuevo, usuario_id, nota) "
            "VALUES (%s,%s,'cancelada',%s,%s)",
            (orden_id, o["estado"], sesion["id"], motivo),
        )
        auditar(cur, sesion, "orden_cancelada", "ordenes", orden_id, f"{o['folio']}: {motivo}")


def obtener_orden(conn, orden_id: int | None = None, folio: str | None = None) -> dict:
    with transaccion(conn) as cur:
        if orden_id is not None:
            cur.execute("SELECT * FROM ordenes WHERE id = %s", (orden_id,))
        else:
            cur.execute("SELECT * FROM ordenes WHERE folio = %s", ((folio or "").strip().upper(),))
        o = cur.fetchone()
        if not o:
            raise ErrorNegocio("Orden no encontrada.")
        cur.execute("SELECT id, nombre, apellidos, telefono FROM clientes WHERE id = %s", (o["cliente_id"],))
        o["cliente"] = cur.fetchone()
        cur.execute("SELECT usuario FROM usuarios WHERE id = %s", (o["usuario_id"],))
        o["recibio"] = cur.fetchone()["usuario"]
        cur.execute(
            "SELECT d.id, d.servicio_id, s.nombre AS servicio, s.unidad, d.descripcion, d.cantidad, "
            "d.precio_unitario, d.importe FROM orden_detalle d JOIN servicios s ON s.id = d.servicio_id "
            "WHERE d.orden_id = %s ORDER BY d.id",
            (o["id"],),
        )
        o["detalle"] = cur.fetchall()
        cur.execute(
            "SELECT p.id, p.tipo, p.monto, p.referencia, p.estado_confirmacion, p.pagado_en, mp.nombre AS metodo FROM pagos p "
            "JOIN metodos_pago mp ON mp.id = p.metodo_pago_id WHERE p.orden_id = %s ORDER BY p.id",
            (o["id"],),
        )
        o["pagos"] = cur.fetchall()
        cur.execute(
            "SELECT h.estado_anterior, h.estado_nuevo, h.cambiado_en, h.nota, u.usuario FROM orden_historial_estado h "
            "JOIN usuarios u ON u.id = h.usuario_id WHERE h.orden_id = %s ORDER BY h.id",
            (o["id"],),
        )
        o["historial"] = cur.fetchall()
        o["pagado"] = pagado_neto_cur(cur, o["id"])
        o["saldo"] = Decimal(o["total"]) - o["pagado"]
        o["por_confirmar"] = pendiente_confirmar_cur(cur, o["id"])
        return o


def listar_ordenes(conn, estados: list[str] | None = None, solo_abiertas: bool = False, cliente_id=None,
                   desde=None, hasta=None, texto_busqueda: str | None = None, limite: int = 200) -> list[dict]:
    where, params = [], []
    if solo_abiertas:
        where.append("o.estado IN ('recibida','en_proceso','lista')")
    if estados:
        malos = [e for e in estados if e not in ESTADOS]
        if malos:
            raise ErrorNegocio(f"Estado desconocido: {malos[0]}")
        where.append("o.estado IN (" + ",".join(["%s"] * len(estados)) + ")")
        params += estados
    if cliente_id:
        where.append("o.cliente_id = %s")
        params.append(cliente_id)
    if desde:
        where.append("DATE(o.fecha_recepcion) >= %s")
        params.append(desde)
    if hasta:
        where.append("DATE(o.fecha_recepcion) <= %s")
        params.append(hasta)
    if texto_busqueda:
        patron = f"%{escapar_like(texto_busqueda.strip())}%"
        where.append("(o.folio LIKE %s OR c.nombre LIKE %s OR c.apellidos LIKE %s OR c.telefono LIKE %s)")
        params += [patron] * 4
    sql = (
        "SELECT o.id, o.folio, o.estado, o.fecha_recepcion, o.fecha_promesa, o.total, "
        "CONCAT_WS(' ', c.nombre, c.apellidos) AS cliente, c.telefono, "
        "COALESCE((SELECT SUM(CASE WHEN p.tipo='reembolso' THEN -p.monto ELSE p.monto END) "
        "FROM pagos p WHERE p.orden_id = o.id), 0) AS pagado "
        "FROM ordenes o LEFT JOIN clientes c ON c.id = o.cliente_id"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY o.fecha_recepcion DESC, o.id DESC LIMIT %s"
    with transaccion(conn) as cur:
        cur.execute(sql, (*params, int(limite)))
        filas = cur.fetchall()
    for f in filas:
        f["saldo"] = Decimal(f["total"]) - Decimal(f["pagado"])
    return filas
