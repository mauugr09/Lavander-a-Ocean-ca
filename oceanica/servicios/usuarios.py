"""Administración de usuarios y contraseñas."""
from __future__ import annotations

from ..db import transaccion
from ..seguridad import ErrorAcceso, hashear, validar_pin, validar_politica, verificar
from .comunes import ErrorNegocio, auditar, requerir_rol, texto


def _validar_password(password: str) -> None:
    problemas = validar_politica(password)
    if problemas:
        raise ErrorNegocio(" ".join(problemas))


def crear_usuario(conn, sesion, usuario: str, password: str, rol: str, empleado_id: int | None = None) -> int:
    requerir_rol(sesion, "administrador")
    usuario = texto(usuario, "usuario", 40)
    _validar_password(password)
    with transaccion(conn) as cur:
        cur.execute("SELECT id FROM roles WHERE nombre = %s", (rol,))
        r = cur.fetchone()
        if not r:
            raise ErrorNegocio(f"Rol desconocido: {rol}")
        cur.execute("SELECT id FROM usuarios WHERE usuario = %s", (usuario,))
        if cur.fetchone():
            raise ErrorNegocio("Ya existe un usuario con ese nombre.")
        if empleado_id is not None:
            cur.execute("SELECT id FROM empleados WHERE id = %s AND activo = 1", (empleado_id,))
            if not cur.fetchone():
                raise ErrorNegocio("El empleado indicado no existe o está dado de baja.")
        cur.execute(
            "INSERT INTO usuarios (rol_id, empleado_id, usuario, password_hash, debe_cambiar_password) "
            "VALUES (%s, %s, %s, %s, 1)",
            (r["id"], empleado_id, usuario, hashear(password)),
        )
        nuevo = cur.lastrowid
        auditar(cur, sesion, "usuario_creado", "usuarios", nuevo, f"{usuario} ({rol})")
        return nuevo


def listar_usuarios(conn, sesion) -> list[dict]:
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        cur.execute(
            "SELECT u.id, u.usuario, r.nombre AS rol, u.activo, u.ultimo_acceso, u.empleado_id, "
            "u.bloqueado_hasta, (u.pin_hash IS NOT NULL) AS tiene_pin FROM usuarios u JOIN roles r ON r.id = u.rol_id ORDER BY u.usuario"
        )
        return cur.fetchall()


def cambiar_password(conn, sesion, actual: str, nueva: str) -> None:
    _validar_password(nueva)
    with transaccion(conn) as cur:
        cur.execute("SELECT password_hash FROM usuarios WHERE id = %s FOR UPDATE", (sesion["id"],))
        fila = cur.fetchone()
        if not fila or not verificar(actual, fila["password_hash"]):
            raise ErrorAcceso("La contraseña actual no es correcta.")
        if verificar(nueva, fila["password_hash"]):
            raise ErrorNegocio("La contraseña nueva debe ser distinta de la actual.")
        cur.execute(
            "UPDATE usuarios SET password_hash = %s, debe_cambiar_password = 0 WHERE id = %s",
            (hashear(nueva), sesion["id"]),
        )
        auditar(cur, sesion, "password_cambiada", "usuarios", sesion["id"])


def restablecer_password(conn, sesion, usuario_id: int, nueva: str) -> None:
    """El administrador asigna una contraseña temporal; el usuario deberá cambiarla."""
    requerir_rol(sesion, "administrador")
    _validar_password(nueva)
    with transaccion(conn) as cur:
        cur.execute(
            "UPDATE usuarios SET password_hash = %s, debe_cambiar_password = 1, "
            "intentos_fallidos = 0, bloqueado_hasta = NULL WHERE id = %s",
            (hashear(nueva), usuario_id),
        )
        if cur.rowcount == 0:
            raise ErrorNegocio("Usuario no encontrado.")
        auditar(cur, sesion, "password_restablecida", "usuarios", usuario_id)


def _admins_activos(cur) -> int:
    cur.execute(
        "SELECT COUNT(*) AS n FROM usuarios u JOIN roles r ON r.id = u.rol_id "
        "WHERE r.nombre = 'administrador' AND u.activo = 1"
    )
    return cur.fetchone()["n"]


def cambiar_estado(conn, sesion, usuario_id: int, activo: bool) -> None:
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        cur.execute(
            "SELECT u.id, u.activo, r.nombre AS rol FROM usuarios u JOIN roles r ON r.id = u.rol_id "
            "WHERE u.id = %s FOR UPDATE",
            (usuario_id,),
        )
        u = cur.fetchone()
        if not u:
            raise ErrorNegocio("Usuario no encontrado.")
        if not activo:
            if usuario_id == sesion["id"]:
                raise ErrorNegocio("No puedes desactivar tu propio usuario.")
            if u["rol"] == "administrador" and u["activo"] and _admins_activos(cur) <= 1:
                raise ErrorNegocio("Debe quedar al menos un administrador activo.")
        cur.execute("UPDATE usuarios SET activo = %s WHERE id = %s", (int(activo), usuario_id))
        auditar(cur, sesion, "usuario_activado" if activo else "usuario_desactivado", "usuarios", usuario_id)


# ---------- PIN de mostrador -------------------------------------------------

def _validar_pin(pin: str) -> None:
    problemas = validar_pin(pin)
    if problemas:
        raise ErrorNegocio(" ".join(problemas))


def asignar_pin(conn, sesion, usuario_id: int, pin: str) -> None:
    """El administrador asigna o restablece el PIN de un empleado (también limpia el bloqueo)."""
    requerir_rol(sesion, "administrador")
    _validar_pin(pin)
    with transaccion(conn) as cur:
        cur.execute("SELECT u.id, r.nombre AS rol FROM usuarios u JOIN roles r ON r.id = u.rol_id "
                    "WHERE u.id = %s FOR UPDATE", (usuario_id,))
        u = cur.fetchone()
        if not u:
            raise ErrorNegocio("Usuario no encontrado.")
        if u["rol"] != "empleado":
            raise ErrorNegocio("El PIN es solo para empleados; el administrador usa su contraseña.")
        cur.execute("UPDATE usuarios SET pin_hash = %s, intentos_fallidos = 0, bloqueado_hasta = NULL WHERE id = %s",
                    (hashear(pin), usuario_id))
        auditar(cur, sesion, "pin_asignado", "usuarios", usuario_id)


def cambiar_pin(conn, sesion, pin_actual: str, pin_nuevo: str) -> None:
    """El empleado cambia su propio PIN confirmando el actual."""
    _validar_pin(pin_nuevo)
    with transaccion(conn) as cur:
        cur.execute("SELECT pin_hash FROM usuarios WHERE id = %s FOR UPDATE", (sesion["id"],))
        fila = cur.fetchone()
        if not fila or not fila["pin_hash"] or not verificar(pin_actual, fila["pin_hash"]):
            raise ErrorAcceso("El PIN actual no es correcto.")
        if verificar(pin_nuevo, fila["pin_hash"]):
            raise ErrorNegocio("El PIN nuevo debe ser distinto del actual.")
        cur.execute("UPDATE usuarios SET pin_hash = %s WHERE id = %s", (hashear(pin_nuevo), sesion["id"]))
        auditar(cur, sesion, "pin_cambiado", "usuarios", sesion["id"])


def listar_para_pin(conn) -> list[dict]:
    """Empleados que pueden identificarse con PIN en la pantalla de mostrador.

    'presente' = ya registró su llegada hoy y no su salida (la pantalla muestra primero a los presentes).
    """
    with transaccion(conn) as cur:
        cur.execute(
            "SELECT u.id AS usuario_id, u.empleado_id, "
            "COALESCE(CONCAT(e.nombre, ' ', e.apellidos), u.usuario) AS nombre, "
            "(a.id IS NOT NULL AND a.hora_entrada IS NOT NULL AND a.hora_salida IS NULL) AS presente "
            "FROM usuarios u JOIN roles r ON r.id = u.rol_id AND r.nombre = 'empleado' "
            "LEFT JOIN empleados e ON e.id = u.empleado_id "
            "LEFT JOIN asistencias a ON a.empleado_id = u.empleado_id AND a.fecha = CURDATE() "
            "WHERE u.activo = 1 AND u.pin_hash IS NOT NULL ORDER BY presente DESC, nombre"
        )
        filas = cur.fetchall()
        for f in filas:
            f["presente"] = bool(f["presente"])
        return filas


def alta_empleado_con_acceso(conn, sesion, nombre, apellidos, fecha_ingreso, pin: str, telefono=None, puesto=None) -> dict:
    """Crea en una sola transacción al empleado, su cuenta de usuario y su PIN de mostrador.

    La cuenta recibe una contraseña aleatoria que nadie conoce: el empleado solo entra con PIN.
    Si algo falla no queda nada a medias. Devuelve {'empleado_id', 'usuario_id', 'usuario'}.
    """
    import re
    import secrets
    import unicodedata

    from .comunes import como_fecha

    requerir_rol(sesion, "administrador")
    _validar_pin(pin)
    datos = (texto(nombre, "nombre", 80), texto(apellidos, "apellidos", 80), texto(telefono, "teléfono", 20, False),
             texto(puesto, "puesto", 60, False), como_fecha(fecha_ingreso, "fecha de ingreso"))
    base = unicodedata.normalize("NFKD", datos[0].split()[0] + datos[1].split()[0][:1]).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]", "", base.lower())[:30] or "empleado"
    with transaccion(conn) as cur:
        cur.execute("SELECT id FROM roles WHERE nombre = 'empleado'")
        rol = cur.fetchone()["id"]
        usuario, n = base, 1
        while True:
            cur.execute("SELECT id FROM usuarios WHERE usuario = %s", (usuario,))
            if not cur.fetchone():
                break
            n += 1
            usuario = f"{base}{n}"
        cur.execute("INSERT INTO empleados (nombre, apellidos, telefono, puesto, fecha_ingreso) VALUES (%s,%s,%s,%s,%s)", datos)
        empleado_id = cur.lastrowid
        cur.execute(
            "INSERT INTO usuarios (rol_id, empleado_id, usuario, password_hash, pin_hash, debe_cambiar_password) "
            "VALUES (%s,%s,%s,%s,%s,0)",
            (rol, empleado_id, usuario, hashear(secrets.token_urlsafe(24)), hashear(pin)),
        )
        usuario_id = cur.lastrowid
        auditar(cur, sesion, "empleado_creado", "empleados", empleado_id, f"{datos[0]} {datos[1]} (usuario {usuario})")
        return {"empleado_id": empleado_id, "usuario_id": usuario_id, "usuario": usuario}
