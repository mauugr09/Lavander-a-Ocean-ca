"""Inventario de insumos, proveedores y movimientos."""
from __future__ import annotations

from decimal import Decimal

from ..db import transaccion
from .comunes import ErrorNegocio, auditar, cantidad, dinero, escapar_like, requerir_rol, texto


# ---------- Categorías y proveedores ----------------------------------------

def listar_categorias(conn) -> list[dict]:
    with transaccion(conn) as cur:
        cur.execute("SELECT id, nombre FROM categorias_insumo ORDER BY nombre")
        return cur.fetchall()


def crear_categoria(conn, sesion, nombre: str) -> int:
    requerir_rol(sesion, "administrador")
    nombre = texto(nombre, "nombre", 60)
    with transaccion(conn) as cur:
        cur.execute("SELECT id FROM categorias_insumo WHERE nombre = %s", (nombre,))
        if cur.fetchone():
            raise ErrorNegocio("Ya existe una categoría con ese nombre.")
        cur.execute("INSERT INTO categorias_insumo (nombre) VALUES (%s)", (nombre,))
        nuevo = cur.lastrowid
        auditar(cur, sesion, "categoria_insumo_creada", "categorias_insumo", nuevo, nombre)
        return nuevo


def listar_proveedores(conn, solo_activos: bool = True) -> list[dict]:
    with transaccion(conn) as cur:
        cur.execute("SELECT * FROM proveedores " + ("WHERE activo = 1 " if solo_activos else "") + "ORDER BY nombre")
        return cur.fetchall()


def crear_proveedor(conn, sesion, nombre: str, contacto=None, telefono=None) -> int:
    requerir_rol(sesion, "administrador")
    nombre = texto(nombre, "nombre", 100)
    contacto = texto(contacto, "contacto", 80, False)
    telefono = texto(telefono, "teléfono", 20, False)
    with transaccion(conn) as cur:
        cur.execute("SELECT id FROM proveedores WHERE nombre = %s", (nombre,))
        if cur.fetchone():
            raise ErrorNegocio("Ya existe un proveedor con ese nombre.")
        cur.execute("INSERT INTO proveedores (nombre, contacto, telefono) VALUES (%s,%s,%s)",
                    (nombre, contacto, telefono))
        nuevo = cur.lastrowid
        auditar(cur, sesion, "proveedor_creado", "proveedores", nuevo, nombre)
        return nuevo


# ---------- Insumos ---------------------------------------------------------

def crear_insumo(conn, sesion, categoria_id: int, nombre: str, unidad: str = "pieza", minimo=0,
                 costo_unitario=0, proveedor_id: int | None = None, existencia_inicial=0) -> int:
    requerir_rol(sesion, "administrador")
    nombre = texto(nombre, "nombre", 80)
    unidad = texto(unidad, "unidad", 15)
    minimo, costo, inicial = dinero(minimo, "mínimo"), dinero(costo_unitario, "costo"), dinero(existencia_inicial, "existencia")
    if min(minimo, costo, inicial) < 0:
        raise ErrorNegocio("Mínimo, costo y existencia no pueden ser negativos.")
    with transaccion(conn) as cur:
        cur.execute("SELECT id FROM categorias_insumo WHERE id = %s", (categoria_id,))
        if not cur.fetchone():
            raise ErrorNegocio("La categoría no existe.")
        if proveedor_id is not None:
            cur.execute("SELECT id FROM proveedores WHERE id = %s AND activo = 1", (proveedor_id,))
            if not cur.fetchone():
                raise ErrorNegocio("El proveedor no existe o está inactivo.")
        cur.execute("SELECT id FROM insumos WHERE nombre = %s", (nombre,))
        if cur.fetchone():
            raise ErrorNegocio("Ya existe un insumo con ese nombre.")
        cur.execute(
            "INSERT INTO insumos (categoria_id, proveedor_id, nombre, unidad, existencia, minimo, costo_unitario) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (categoria_id, proveedor_id, nombre, unidad, inicial, minimo, costo),
        )
        nuevo = cur.lastrowid
        if inicial > 0:
            cur.execute(
                "INSERT INTO movimientos_inventario (insumo_id, usuario_id, tipo, cantidad, costo_unitario, "
                "existencia_resultante, motivo) VALUES (%s,%s,'entrada',%s,%s,%s,'Existencia inicial')",
                (nuevo, sesion["id"], inicial, costo, inicial),
            )
        auditar(cur, sesion, "insumo_creado", "insumos", nuevo, nombre)
        return nuevo


def actualizar_insumo(conn, sesion, insumo_id: int, nombre=None, unidad=None, minimo=None, costo_unitario=None,
                      proveedor_id=None, categoria_id=None) -> None:
    """La existencia no se edita aquí: se cambia con movimientos o con ajustar_existencia."""
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        cur.execute("SELECT * FROM insumos WHERE id = %s FOR UPDATE", (insumo_id,))
        i = cur.fetchone()
        if not i:
            raise ErrorNegocio("Insumo no encontrado.")
        nuevo = {
            "nombre": texto(nombre, "nombre", 80) if nombre is not None else i["nombre"],
            "unidad": texto(unidad, "unidad", 15) if unidad is not None else i["unidad"],
            "minimo": dinero(minimo, "mínimo") if minimo is not None else i["minimo"],
            "costo_unitario": dinero(costo_unitario, "costo") if costo_unitario is not None else i["costo_unitario"],
            "proveedor_id": proveedor_id if proveedor_id is not None else i["proveedor_id"],
            "categoria_id": categoria_id if categoria_id is not None else i["categoria_id"],
        }
        if nuevo["minimo"] < 0 or nuevo["costo_unitario"] < 0:
            raise ErrorNegocio("Mínimo y costo no pueden ser negativos.")
        if nuevo["nombre"] != i["nombre"]:
            cur.execute("SELECT id FROM insumos WHERE nombre = %s AND id <> %s", (nuevo["nombre"], insumo_id))
            if cur.fetchone():
                raise ErrorNegocio("Ya existe un insumo con ese nombre.")
        cur.execute(
            "UPDATE insumos SET nombre=%s, unidad=%s, minimo=%s, costo_unitario=%s, proveedor_id=%s, categoria_id=%s "
            "WHERE id=%s",
            (nuevo["nombre"], nuevo["unidad"], nuevo["minimo"], nuevo["costo_unitario"], nuevo["proveedor_id"],
             nuevo["categoria_id"], insumo_id),
        )
        auditar(cur, sesion, "insumo_actualizado", "insumos", insumo_id, nuevo["nombre"])


def cambiar_estado_insumo(conn, sesion, insumo_id: int, activo: bool) -> None:
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        cur.execute("UPDATE insumos SET activo = %s WHERE id = %s", (int(activo), insumo_id))
        if cur.rowcount == 0:
            raise ErrorNegocio("Insumo no encontrado.")
        auditar(cur, sesion, "insumo_activado" if activo else "insumo_desactivado", "insumos", insumo_id)


def listar_insumos(conn, solo_bajos: bool = False, texto_busqueda: str | None = None,
                   solo_activos: bool = True) -> list[dict]:
    where, params = [], []
    if solo_activos:
        where.append("i.activo = 1")
    if solo_bajos:
        where.append("i.existencia <= i.minimo")
    if texto_busqueda:
        where.append("i.nombre LIKE %s")
        params.append(f"%{escapar_like(texto_busqueda.strip())}%")
    sql = ("SELECT i.*, c.nombre AS categoria, p.nombre AS proveedor, (i.existencia <= i.minimo) AS bajo "
           "FROM insumos i JOIN categorias_insumo c ON c.id = i.categoria_id "
           "LEFT JOIN proveedores p ON p.id = i.proveedor_id")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY i.nombre"
    with transaccion(conn) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


# ---------- Movimientos -----------------------------------------------------

def registrar_movimiento(conn, sesion, insumo_id: int, tipo: str, cant, motivo: str | None = None,
                         costo_unitario=None) -> dict:
    """Entrada (compra, devolución) o salida (consumo, merma). Devuelve el insumo actualizado."""
    requerir_rol(sesion, "administrador", "empleado")
    if tipo not in ("entrada", "salida"):
        raise ErrorNegocio("Usa 'entrada' o 'salida'. Para corregir existencias usa ajustar_existencia.")
    cant = cantidad(cant)
    motivo = texto(motivo, "motivo", 120, tipo == "salida")
    costo = dinero(costo_unitario, "costo") if costo_unitario is not None else None
    if costo is not None and costo < 0:
        raise ErrorNegocio("El costo no puede ser negativo.")
    with transaccion(conn) as cur:
        cur.execute("SELECT * FROM insumos WHERE id = %s AND activo = 1 FOR UPDATE", (insumo_id,))
        i = cur.fetchone()
        if not i:
            raise ErrorNegocio("Insumo no encontrado o inactivo.")
        actual = Decimal(i["existencia"])
        nueva = actual + cant if tipo == "entrada" else actual - cant
        if nueva < 0:
            raise ErrorNegocio(f"No hay suficiente '{i['nombre']}': existencia {actual} {i['unidad']}.")
        nuevo_costo = costo if (tipo == "entrada" and costo is not None) else i["costo_unitario"]
        cur.execute("UPDATE insumos SET existencia = %s, costo_unitario = %s WHERE id = %s",
                    (nueva, nuevo_costo, insumo_id))
        cur.execute(
            "INSERT INTO movimientos_inventario (insumo_id, usuario_id, tipo, cantidad, costo_unitario, "
            "existencia_resultante, motivo) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (insumo_id, sesion["id"], tipo, cant, costo, nueva, motivo),
        )
        auditar(cur, sesion, f"insumo_{tipo}", "insumos", insumo_id, f"{i['nombre']} {cant}")
        i.update(existencia=nueva, costo_unitario=nuevo_costo, bajo=nueva <= Decimal(i["minimo"]))
        return i


def ajustar_existencia(conn, sesion, insumo_id: int, existencia_real, motivo: str) -> dict:
    """Fija la existencia al conteo físico (solo administrador). Queda registrado el cambio."""
    requerir_rol(sesion, "administrador")
    real = dinero(existencia_real, "existencia real")
    if real < 0:
        raise ErrorNegocio("La existencia no puede ser negativa.")
    motivo = texto(motivo, "motivo", 100)
    with transaccion(conn) as cur:
        cur.execute("SELECT * FROM insumos WHERE id = %s FOR UPDATE", (insumo_id,))
        i = cur.fetchone()
        if not i:
            raise ErrorNegocio("Insumo no encontrado.")
        actual = Decimal(i["existencia"])
        if real == actual:
            raise ErrorNegocio("La existencia real coincide con la registrada; no hay nada que ajustar.")
        cur.execute("UPDATE insumos SET existencia = %s WHERE id = %s", (real, insumo_id))
        cur.execute(
            "INSERT INTO movimientos_inventario (insumo_id, usuario_id, tipo, cantidad, existencia_resultante, motivo) "
            "VALUES (%s,%s,'ajuste',%s,%s,%s)",
            (insumo_id, sesion["id"], abs(real - actual), real, f"{motivo} ({actual} -> {real})"[:120]),
        )
        auditar(cur, sesion, "insumo_ajuste", "insumos", insumo_id, f"{i['nombre']}: {actual} -> {real}")
        i.update(existencia=real, bajo=real <= Decimal(i["minimo"]))
        return i


def movimientos_insumo(conn, insumo_id: int, limite: int = 100) -> list[dict]:
    with transaccion(conn) as cur:
        cur.execute(
            "SELECT m.id, m.tipo, m.cantidad, m.costo_unitario, m.existencia_resultante, m.motivo, m.creado_en, "
            "u.usuario FROM movimientos_inventario m JOIN usuarios u ON u.id = m.usuario_id "
            "WHERE m.insumo_id = %s ORDER BY m.id DESC LIMIT %s",
            (insumo_id, int(limite)),
        )
        return cur.fetchall()
