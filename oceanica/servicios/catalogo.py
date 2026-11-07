"""Categorías y servicios (con sus precios)."""
from __future__ import annotations

from ..db import transaccion
from .comunes import ErrorNegocio, auditar, dinero, requerir_rol, texto

UNIDADES = ("kilo", "pieza")


def listar_categorias(conn, solo_activas: bool = True) -> list[dict]:
    with transaccion(conn) as cur:
        cur.execute(
            "SELECT id, nombre, activo FROM categorias_servicio "
            + ("WHERE activo = 1 " if solo_activas else "") + "ORDER BY nombre"
        )
        return cur.fetchall()


def crear_categoria(conn, sesion, nombre: str) -> int:
    requerir_rol(sesion, "administrador")
    nombre = texto(nombre, "nombre", 60)
    with transaccion(conn) as cur:
        cur.execute("SELECT id FROM categorias_servicio WHERE nombre = %s", (nombre,))
        if cur.fetchone():
            raise ErrorNegocio("Ya existe una categoría con ese nombre.")
        cur.execute("INSERT INTO categorias_servicio (nombre) VALUES (%s)", (nombre,))
        nuevo = cur.lastrowid
        auditar(cur, sesion, "categoria_servicio_creada", "categorias_servicio", nuevo, nombre)
        return nuevo


def listar_servicios(conn, solo_activos: bool = True, categoria_id: int | None = None) -> list[dict]:
    where, params = [], []
    if solo_activos:
        where.append("s.activo = 1")
    if categoria_id:
        where.append("s.categoria_id = %s")
        params.append(categoria_id)
    sql = ("SELECT s.id, s.nombre, s.unidad, s.precio, s.activo, s.categoria_id, c.nombre AS categoria "
           "FROM servicios s JOIN categorias_servicio c ON c.id = s.categoria_id")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY c.nombre, s.nombre"
    with transaccion(conn) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def crear_servicio(conn, sesion, categoria_id: int, nombre: str, unidad: str, precio) -> int:
    requerir_rol(sesion, "administrador")
    nombre = texto(nombre, "nombre", 80)
    if unidad not in UNIDADES:
        raise ErrorNegocio("La unidad debe ser 'kilo' o 'pieza'.")
    precio = dinero(precio, "precio")
    if precio < 0:
        raise ErrorNegocio("El precio no puede ser negativo.")
    with transaccion(conn) as cur:
        cur.execute("SELECT id FROM categorias_servicio WHERE id = %s AND activo = 1", (categoria_id,))
        if not cur.fetchone():
            raise ErrorNegocio("La categoría no existe o está inactiva.")
        cur.execute("SELECT id FROM servicios WHERE nombre = %s", (nombre,))
        if cur.fetchone():
            raise ErrorNegocio("Ya existe un servicio con ese nombre.")
        cur.execute(
            "INSERT INTO servicios (categoria_id, nombre, unidad, precio) VALUES (%s,%s,%s,%s)",
            (categoria_id, nombre, unidad, precio),
        )
        nuevo = cur.lastrowid
        auditar(cur, sesion, "servicio_creado", "servicios", nuevo, f"{nombre} ${precio}/{unidad}")
        return nuevo


def actualizar_servicio(conn, sesion, servicio_id: int, nombre=None, unidad=None, precio=None,
                        categoria_id=None) -> None:
    """Cambiar el precio no altera órdenes anteriores: guardan su propio precio."""
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        cur.execute("SELECT * FROM servicios WHERE id = %s FOR UPDATE", (servicio_id,))
        s = cur.fetchone()
        if not s:
            raise ErrorNegocio("Servicio no encontrado.")
        nuevo = {
            "nombre": texto(nombre, "nombre", 80) if nombre is not None else s["nombre"],
            "unidad": unidad if unidad is not None else s["unidad"],
            "precio": dinero(precio, "precio") if precio is not None else s["precio"],
            "categoria_id": categoria_id if categoria_id is not None else s["categoria_id"],
        }
        if nuevo["unidad"] not in UNIDADES:
            raise ErrorNegocio("La unidad debe ser 'kilo' o 'pieza'.")
        if nuevo["precio"] < 0:
            raise ErrorNegocio("El precio no puede ser negativo.")
        if nuevo["nombre"] != s["nombre"]:
            cur.execute("SELECT id FROM servicios WHERE nombre = %s AND id <> %s", (nuevo["nombre"], servicio_id))
            if cur.fetchone():
                raise ErrorNegocio("Ya existe un servicio con ese nombre.")
        cur.execute(
            "UPDATE servicios SET nombre=%s, unidad=%s, precio=%s, categoria_id=%s WHERE id=%s",
            (nuevo["nombre"], nuevo["unidad"], nuevo["precio"], nuevo["categoria_id"], servicio_id),
        )
        detalle = f"{s['nombre']}: ${s['precio']} -> ${nuevo['precio']}" if nuevo["precio"] != s["precio"] else s["nombre"]
        auditar(cur, sesion, "servicio_actualizado", "servicios", servicio_id, detalle)


def cambiar_estado_servicio(conn, sesion, servicio_id: int, activo: bool) -> None:
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        cur.execute("UPDATE servicios SET activo = %s WHERE id = %s", (int(activo), servicio_id))
        if cur.rowcount == 0:
            raise ErrorNegocio("Servicio no encontrado.")
        auditar(cur, sesion, "servicio_activado" if activo else "servicio_desactivado", "servicios", servicio_id)
