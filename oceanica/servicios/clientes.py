"""Clientes de la lavandería."""
from __future__ import annotations

from ..db import transaccion
from .comunes import ErrorNegocio, auditar, escapar_like, requerir_rol, texto
from .facturacion import CAMPOS_FISCALES, validar_datos_fiscales


def crear_cliente(conn, sesion, nombre, apellidos=None, telefono=None, email=None, notas=None, **fiscales) -> int:
    """`fiscales` (opcionales): rfc, razon_social, regimen_fiscal, uso_cfdi, codigo_postal_fiscal."""
    requerir_rol(sesion, "administrador", "empleado")
    desconocidos = set(fiscales) - set(CAMPOS_FISCALES)
    if desconocidos:
        raise ErrorNegocio(f"Campos no editables: {', '.join(sorted(desconocidos))}")
    datos = {
        "nombre": texto(nombre, "nombre", 80),
        "apellidos": texto(apellidos, "apellidos", 80, False),
        "telefono": texto(telefono, "teléfono", 20, False),
        "email": texto(email, "correo", 120, False),
        "notas": texto(notas, "notas", 300, False),
        **validar_datos_fiscales(fiscales),
    }
    if datos["email"] and "@" not in datos["email"]:
        raise ErrorNegocio("El correo no es válido.")
    with transaccion(conn) as cur:
        cur.execute(f"INSERT INTO clientes ({', '.join(datos)}) VALUES ({', '.join(['%s'] * len(datos))})",
                    tuple(datos.values()))
        nuevo = cur.lastrowid
        auditar(cur, sesion, "cliente_creado", "clientes", nuevo)
        return nuevo


def actualizar_cliente(conn, sesion, cliente_id: int, **cambios) -> None:
    requerir_rol(sesion, "administrador", "empleado")
    limites = {"nombre": 80, "apellidos": 80, "telefono": 20, "email": 120, "notas": 300}
    desconocidos = set(cambios) - set(limites) - set(CAMPOS_FISCALES)
    if desconocidos:
        raise ErrorNegocio(f"Campos no editables: {', '.join(sorted(desconocidos))}")
    if not cambios:
        return
    valores = {c: texto(v, c, limites[c], obligatorio=(c == "nombre")) for c, v in cambios.items() if c in limites}
    valores.update(validar_datos_fiscales({c: v for c, v in cambios.items() if c in CAMPOS_FISCALES}))
    if valores.get("email") and "@" not in valores["email"]:
        raise ErrorNegocio("El correo no es válido.")
    sets = ", ".join(f"{c} = %s" for c in valores)
    with transaccion(conn) as cur:
        cur.execute(f"UPDATE clientes SET {sets} WHERE id = %s", (*valores.values(), cliente_id))
        if cur.rowcount == 0:
            cur.execute("SELECT id FROM clientes WHERE id = %s", (cliente_id,))
            if not cur.fetchone():
                raise ErrorNegocio("Cliente no encontrado.")
        auditar(cur, sesion, "cliente_actualizado", "clientes", cliente_id, ", ".join(valores))


def cambiar_estado(conn, sesion, cliente_id: int, activo: bool) -> None:
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        cur.execute("UPDATE clientes SET activo = %s WHERE id = %s", (int(activo), cliente_id))
        auditar(cur, sesion, "cliente_activado" if activo else "cliente_desactivado", "clientes", cliente_id)


def obtener_cliente(conn, cliente_id: int) -> dict:
    with transaccion(conn) as cur:
        cur.execute("SELECT * FROM clientes WHERE id = %s", (cliente_id,))
        c = cur.fetchone()
        if not c:
            raise ErrorNegocio("Cliente no encontrado.")
        return c


def buscar_clientes(conn, consulta: str = "", solo_activos: bool = True, limite: int = 50) -> list[dict]:
    """Busca por nombre, apellidos, teléfono o RFC (coincidencia parcial)."""
    partes = [p for p in (consulta or "").split() if p]
    where, params = [], []
    if solo_activos:
        where.append("activo = 1")
    for p in partes:
        patron = f"%{escapar_like(p)}%"
        where.append("(nombre LIKE %s OR apellidos LIKE %s OR telefono LIKE %s OR rfc LIKE %s)")
        params += [patron] * 4
    sql = "SELECT * FROM clientes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY nombre, apellidos LIMIT %s"
    with transaccion(conn) as cur:
        cur.execute(sql, (*params, int(limite)))
        return cur.fetchall()


def historial_ordenes(conn, cliente_id: int, limite: int = 100) -> list[dict]:
    with transaccion(conn) as cur:
        cur.execute(
            "SELECT s.orden_id, s.folio, s.estado, s.fecha_recepcion, s.total, s.pagado, s.saldo "
            "FROM v_saldo_ordenes s WHERE s.cliente_id = %s ORDER BY s.fecha_recepcion DESC LIMIT %s",
            (cliente_id, int(limite)),
        )
        return cur.fetchall()
