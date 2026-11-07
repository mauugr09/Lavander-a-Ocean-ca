"""Caja: cortes, pagos, anticipos, reembolsos, gastos y retiros."""
from __future__ import annotations

from decimal import Decimal

from ..db import transaccion
from .comunes import CERO, ErrorNegocio, auditar, dinero, es_admin, requerir_rol, texto

_SIGNO_PAGO = "CASE WHEN p.tipo = 'reembolso' THEN -p.monto ELSE p.monto END"


# ---------- utilidades internas (reciben el cursor de una transacción) --------

def corte_abierto_cur(cur, bloquear: bool = False) -> dict | None:
    cur.execute(
        "SELECT * FROM cortes_caja WHERE estado = 'abierto' ORDER BY id DESC LIMIT 1"
        + (" FOR UPDATE" if bloquear else "")
    )
    return cur.fetchone()


def pagado_neto_cur(cur, orden_id: int) -> Decimal:
    cur.execute(
        f"SELECT COALESCE(SUM({_SIGNO_PAGO}), 0) AS neto FROM pagos p WHERE p.orden_id = %s", (orden_id,)
    )
    return Decimal(cur.fetchone()["neto"])


def pagado_confirmado_cur(cur, orden_id: int) -> Decimal:
    """Pagado neto sin contar transferencias por confirmar ni rechazadas."""
    cur.execute(
        f"SELECT COALESCE(SUM({_SIGNO_PAGO}), 0) AS neto FROM pagos p "
        "WHERE p.orden_id = %s AND p.estado_confirmacion = 'confirmado'", (orden_id,)
    )
    return Decimal(cur.fetchone()["neto"])


def pendiente_confirmar_cur(cur, orden_id: int) -> Decimal:
    cur.execute("SELECT COALESCE(SUM(monto), 0) AS n FROM pagos WHERE orden_id = %s AND estado_confirmacion = 'pendiente'",
                (orden_id,))
    return Decimal(cur.fetchone()["n"])


def registrar_pago_cur(cur, sesion, orden_id, metodo_pago_id, monto, tipo="pago", referencia=None) -> int:
    if tipo not in ("pago", "anticipo", "reembolso"):
        raise ErrorNegocio("Tipo de pago no válido.")
    monto = dinero(monto, "monto")
    if monto <= 0:
        raise ErrorNegocio("El monto debe ser mayor que cero.")
    referencia = texto(referencia, "referencia", 60, False)
    corte = corte_abierto_cur(cur)
    if not corte:
        raise ErrorNegocio("No hay caja abierta. Abre la caja antes de cobrar.")
    cur.execute("SELECT id, total, estado FROM ordenes WHERE id = %s FOR UPDATE", (orden_id,))
    orden = cur.fetchone()
    if not orden:
        raise ErrorNegocio("Orden no encontrada.")
    if orden["estado"] == "cancelada":
        raise ErrorNegocio("La orden está cancelada.")
    cur.execute("SELECT id, nombre, requiere_confirmacion FROM metodos_pago WHERE id = %s AND activo = 1",
                (metodo_pago_id,))
    metodo = cur.fetchone()
    if not metodo:
        raise ErrorNegocio("Método de pago no válido.")
    por_confirmar = bool(metodo["requiere_confirmacion"]) and tipo != "reembolso"
    if por_confirmar and not referencia:
        raise ErrorNegocio(f"Captura la clave de rastreo o referencia de la {metodo['nombre'].lower()}.")
    pagado = pagado_neto_cur(cur, orden_id)
    if tipo == "reembolso":
        if not es_admin(sesion):
            raise ErrorNegocio("Solo el administrador puede registrar reembolsos.")
        if pendiente_confirmar_cur(cur, orden_id) > 0:
            raise ErrorNegocio("La orden tiene transferencias por confirmar. Confírmalas o recházalas antes de reembolsar.")
        if monto > pagado:
            raise ErrorNegocio(f"No se puede reembolsar más de lo pagado (${pagado}).")
    else:
        saldo = Decimal(orden["total"]) - pagado
        if saldo <= 0:
            raise ErrorNegocio("La orden ya está pagada por completo.")
        if monto > saldo:
            raise ErrorNegocio(f"El monto excede el saldo pendiente (${saldo}).")
    cur.execute(
        "INSERT INTO pagos (orden_id, metodo_pago_id, corte_id, usuario_id, monto, tipo, referencia, estado_confirmacion) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (orden_id, metodo_pago_id, corte["id"], sesion["id"], monto, tipo, referencia,
         "pendiente" if por_confirmar else "confirmado"),
    )
    pago_id = cur.lastrowid
    auditar(cur, sesion, f"{tipo}_registrado", "pagos", pago_id, f"orden {orden_id} ${monto}")
    return pago_id


def registrar_movimiento_cur(cur, sesion, tipo, concepto, monto) -> int:
    if tipo not in ("gasto", "retiro", "ingreso"):
        raise ErrorNegocio("Tipo de movimiento no válido.")
    if tipo == "retiro":
        requerir_rol(sesion, "administrador")
    concepto = texto(concepto, "concepto", 120)
    monto = dinero(monto, "monto")
    if monto <= 0:
        raise ErrorNegocio("El monto debe ser mayor que cero.")
    corte = corte_abierto_cur(cur)
    if not corte:
        raise ErrorNegocio("No hay caja abierta.")
    cur.execute(
        "INSERT INTO movimientos_caja (corte_id, usuario_id, tipo, concepto, monto) VALUES (%s,%s,%s,%s,%s)",
        (corte["id"], sesion["id"], tipo, concepto, monto),
    )
    mov_id = cur.lastrowid
    auditar(cur, sesion, f"caja_{tipo}", "movimientos_caja", mov_id, f"{concepto} ${monto}")
    return mov_id


def resumen_corte_cur(cur, corte_id: int) -> dict:
    cur.execute("SELECT * FROM cortes_caja WHERE id = %s", (corte_id,))
    corte = cur.fetchone()
    if not corte:
        raise ErrorNegocio("Corte no encontrado.")
    cur.execute(
        f"SELECT mp.nombre AS metodo, mp.es_efectivo, COALESCE(SUM({_SIGNO_PAGO}), 0) AS total "
        "FROM pagos p JOIN metodos_pago mp ON mp.id = p.metodo_pago_id "
        "WHERE p.corte_id = %s GROUP BY mp.id, mp.nombre, mp.es_efectivo ORDER BY mp.nombre",
        (corte_id,),
    )
    por_metodo = cur.fetchall()
    cur.execute(
        "SELECT tipo, COALESCE(SUM(monto), 0) AS total FROM movimientos_caja WHERE corte_id = %s GROUP BY tipo",
        (corte_id,),
    )
    mov = {f["tipo"]: Decimal(f["total"]) for f in cur.fetchall()}
    efectivo = sum((Decimal(m["total"]) for m in por_metodo if m["es_efectivo"]), CERO)
    total_cobrado = sum((Decimal(m["total"]) for m in por_metodo), CERO)
    ingresos, gastos, retiros = (mov.get(k, CERO) for k in ("ingreso", "gasto", "retiro"))
    esperado = Decimal(corte["fondo_inicial"]) + efectivo + ingresos - gastos - retiros
    cur.execute("SELECT COUNT(*) AS n, COALESCE(SUM(monto), 0) AS total FROM pagos "
                "WHERE corte_id = %s AND estado_confirmacion = 'pendiente'", (corte_id,))
    pend = cur.fetchone()
    return {
        "transferencias_pendientes": {"cantidad": pend["n"], "total": Decimal(pend["total"])},
        "corte": corte,
        "por_metodo": por_metodo,
        "total_cobrado": total_cobrado,
        "efectivo_cobrado": efectivo,
        "ingresos": ingresos,
        "gastos": gastos,
        "retiros": retiros,
        "efectivo_esperado": esperado,
    }


# ---------- API pública -------------------------------------------------------

def listar_metodos(conn) -> list[dict]:
    with transaccion(conn) as cur:
        cur.execute("SELECT id, nombre, es_efectivo, requiere_confirmacion FROM metodos_pago WHERE activo = 1 ORDER BY id")
        return cur.fetchall()


def abrir_corte(conn, sesion, fondo_inicial=0) -> int:
    requerir_rol(sesion, "administrador", "empleado")
    fondo = dinero(fondo_inicial, "fondo inicial")
    if fondo < 0:
        raise ErrorNegocio("El fondo inicial no puede ser negativo.")
    with transaccion(conn) as cur:
        if corte_abierto_cur(cur, bloquear=True):
            raise ErrorNegocio("Ya hay una caja abierta. Ciérrala antes de abrir otra.")
        cur.execute(
            "INSERT INTO cortes_caja (usuario_apertura_id, fondo_inicial) VALUES (%s, %s)", (sesion["id"], fondo)
        )
        nuevo = cur.lastrowid
        auditar(cur, sesion, "caja_abierta", "cortes_caja", nuevo, f"fondo ${fondo}")
        return nuevo


def corte_abierto(conn) -> dict | None:
    with transaccion(conn) as cur:
        return corte_abierto_cur(cur)


def registrar_pago(conn, sesion, orden_id, metodo_pago_id, monto, tipo="pago", referencia=None) -> int:
    requerir_rol(sesion, "administrador", "empleado")
    with transaccion(conn) as cur:
        return registrar_pago_cur(cur, sesion, orden_id, metodo_pago_id, monto, tipo, referencia)


def registrar_movimiento(conn, sesion, tipo, concepto, monto) -> int:
    requerir_rol(sesion, "administrador", "empleado")
    with transaccion(conn) as cur:
        return registrar_movimiento_cur(cur, sesion, tipo, concepto, monto)


def resumen_corte(conn, corte_id: int | None = None) -> dict:
    """Resumen del corte indicado o, si no se da, del que está abierto."""
    with transaccion(conn) as cur:
        if corte_id is None:
            abierto = corte_abierto_cur(cur)
            if not abierto:
                raise ErrorNegocio("No hay caja abierta.")
            corte_id = abierto["id"]
        return resumen_corte_cur(cur, corte_id)


def movimientos_corte(conn, corte_id: int) -> list[dict]:
    with transaccion(conn) as cur:
        cur.execute(
            "SELECT m.id, m.tipo, m.concepto, m.monto, m.creado_en, u.usuario FROM movimientos_caja m "
            "JOIN usuarios u ON u.id = m.usuario_id WHERE m.corte_id = %s ORDER BY m.id",
            (corte_id,),
        )
        return cur.fetchall()


def cerrar_corte(conn, sesion, efectivo_contado, observaciones=None) -> dict:
    requerir_rol(sesion, "administrador", "empleado")
    contado = dinero(efectivo_contado, "efectivo contado")
    if contado < 0:
        raise ErrorNegocio("El efectivo contado no puede ser negativo.")
    observaciones = texto(observaciones, "observaciones", 200, False)
    with transaccion(conn) as cur:
        corte = corte_abierto_cur(cur, bloquear=True)
        if not corte:
            raise ErrorNegocio("No hay caja abierta.")
        resumen = resumen_corte_cur(cur, corte["id"])
        diferencia = contado - resumen["efectivo_esperado"]
        if diferencia != 0 and not observaciones:
            raise ErrorNegocio(
                f"Hay una diferencia de ${diferencia} contra lo esperado "
                f"(${resumen['efectivo_esperado']}). Anota una observación para cerrar."
            )
        cur.execute(
            "UPDATE cortes_caja SET estado='cerrado', cerrada_en=NOW(), usuario_cierre_id=%s, "
            "efectivo_esperado=%s, efectivo_contado=%s, diferencia=%s, observaciones=%s WHERE id=%s",
            (sesion["id"], resumen["efectivo_esperado"], contado, diferencia, observaciones, corte["id"]),
        )
        auditar(cur, sesion, "caja_cerrada", "cortes_caja", corte["id"], f"diferencia ${diferencia}")
        resumen["efectivo_contado"] = contado
        resumen["diferencia"] = diferencia
        return resumen


def listar_cortes(conn, desde=None, hasta=None, limite: int = 100) -> list[dict]:
    where, params = [], []
    if desde:
        where.append("DATE(abierta_en) >= %s")
        params.append(desde)
    if hasta:
        where.append("DATE(abierta_en) <= %s")
        params.append(hasta)
    sql = "SELECT * FROM cortes_caja" + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY id DESC LIMIT %s"
    with transaccion(conn) as cur:
        cur.execute(sql, (*params, int(limite)))
        return cur.fetchall()


# ---------- Transferencias por confirmar (solo administrador) ------------------

def listar_transferencias_pendientes(conn, sesion) -> list[dict]:
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        cur.execute(
            "SELECT p.id, p.orden_id, o.folio, p.monto, p.referencia, p.pagado_en, u.usuario AS cobro, "
            "o.estado AS estado_orden FROM pagos p JOIN ordenes o ON o.id = p.orden_id "
            "JOIN usuarios u ON u.id = p.usuario_id WHERE p.estado_confirmacion = 'pendiente' ORDER BY p.id"
        )
        return cur.fetchall()


def _pago_pendiente(cur, pago_id: int) -> dict:
    cur.execute("SELECT * FROM pagos WHERE id = %s FOR UPDATE", (pago_id,))
    p = cur.fetchone()
    if not p:
        raise ErrorNegocio("Pago no encontrado.")
    if p["estado_confirmacion"] != "pendiente":
        raise ErrorNegocio(f"Este pago ya está {p['estado_confirmacion']}.")
    return p


def confirmar_transferencia(conn, sesion, pago_id: int) -> None:
    """El administrador confirma que el dinero llegó al banco."""
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        p = _pago_pendiente(cur, pago_id)
        cur.execute("UPDATE pagos SET estado_confirmacion = 'confirmado', confirmado_por = %s, confirmado_en = NOW() "
                    "WHERE id = %s", (sesion["id"], pago_id))
        auditar(cur, sesion, "transferencia_confirmada", "pagos", pago_id, f"orden {p['orden_id']} ${p['monto']}")


def rechazar_transferencia(conn, sesion, pago_id: int, motivo: str) -> None:
    """La transferencia nunca llegó: se compensa con un reembolso interno y la orden recupera su saldo.

    Requiere caja abierta (el contraasiento queda en el corte vigente; no mueve efectivo).
    """
    requerir_rol(sesion, "administrador")
    motivo = texto(motivo, "motivo", 120)
    with transaccion(conn) as cur:
        p = _pago_pendiente(cur, pago_id)
        corte = corte_abierto_cur(cur)
        if not corte:
            raise ErrorNegocio("Abre la caja para registrar el rechazo.")
        cur.execute("UPDATE pagos SET estado_confirmacion = 'rechazado', confirmado_por = %s, confirmado_en = NOW() "
                    "WHERE id = %s", (sesion["id"], pago_id))
        cur.execute(
            "INSERT INTO pagos (orden_id, metodo_pago_id, corte_id, usuario_id, monto, tipo, referencia, "
            "estado_confirmacion, confirmado_por, confirmado_en) VALUES (%s,%s,%s,%s,%s,'reembolso',%s,'rechazado',%s,NOW())",
            (p["orden_id"], p["metodo_pago_id"], corte["id"], sesion["id"], p["monto"],
             f"Rechazo del pago #{pago_id}: {motivo}"[:60], sesion["id"]),
        )
        auditar(cur, sesion, "transferencia_rechazada", "pagos", pago_id, f"orden {p['orden_id']} ${p['monto']}: {motivo}")
