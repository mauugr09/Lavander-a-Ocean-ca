"""Contraseñas, inicio de sesión con bloqueo y bitácora."""
from __future__ import annotations

from datetime import datetime, timedelta

import bcrypt

MAX_INTENTOS = 5
MINUTOS_BLOQUEO = 15
LONGITUD_MINIMA = 8
BCRYPT_ROUNDS = 12
LONGITUD_PIN = (4, 6)


class ErrorAcceso(Exception):
    """Usuario o contraseña inválidos, o cuenta bloqueada/inactiva."""


def validar_politica(password: str) -> list[str]:
    """Devuelve la lista de problemas; vacía si la contraseña es aceptable."""
    problemas = []
    if len(password) < LONGITUD_MINIMA:
        problemas.append(f"Debe tener al menos {LONGITUD_MINIMA} caracteres.")
    if password.isdigit():
        problemas.append("No puede ser solo números.")
    if password.strip() != password or " " in password[:1]:
        problemas.append("No debe empezar ni terminar con espacios.")
    return problemas


def hashear(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("ascii")


def verificar(password: str, hash_guardado: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hash_guardado.encode("ascii"))
    except ValueError:
        return False


def esta_bloqueado(bloqueado_hasta: datetime | None, ahora: datetime) -> bool:
    return bloqueado_hasta is not None and bloqueado_hasta > ahora


def registrar_auditoria(cur, usuario_id, accion, tabla=None, registro_id=None, detalle=None):
    cur.execute(
        "INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, detalle) "
        "VALUES (%s, %s, %s, %s, %s)",
        (usuario_id, accion, tabla, registro_id, (detalle or "")[:500] or None),
    )


def _autenticar(conn, filtro: str, valor, secreto: str, columna_hash: str, mensaje: str,
                ahora: datetime | None, solo_empleado: bool = False) -> dict:
    """Valida un secreto (contraseña o PIN) con bloqueo compartido tras MAX_INTENTOS fallos.

    El mensaje de error es el mismo para usuario inexistente y secreto incorrecto,
    para no revelar qué usuarios existen.
    """
    ahora = ahora or datetime.now()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            f"SELECT u.id, u.usuario, u.{columna_hash}, u.activo, u.intentos_fallidos, "
            "u.bloqueado_hasta, u.debe_cambiar_password, u.empleado_id, r.nombre AS rol "
            "FROM usuarios u JOIN roles r ON r.id = u.rol_id "
            f"WHERE {filtro} FOR UPDATE",
            (valor,),
        )
        fila = cur.fetchone()
        if not fila or not fila["activo"] or not fila[columna_hash]:
            conn.rollback()
            raise ErrorAcceso(mensaje)
        if solo_empleado and fila["rol"] != "empleado":
            conn.rollback()
            raise ErrorAcceso("Los administradores inician sesión con su contraseña.")
        if esta_bloqueado(fila["bloqueado_hasta"], ahora):
            conn.rollback()
            raise ErrorAcceso("Cuenta bloqueada temporalmente. Intenta más tarde.")

        if not verificar(secreto, fila[columna_hash]):
            intentos = fila["intentos_fallidos"] + 1
            bloqueo = ahora + timedelta(minutes=MINUTOS_BLOQUEO) if intentos >= MAX_INTENTOS else None
            cur.execute(
                "UPDATE usuarios SET intentos_fallidos = %s, bloqueado_hasta = %s WHERE id = %s",
                (0 if bloqueo else intentos, bloqueo, fila["id"]),
            )
            registrar_auditoria(cur, fila["id"], "login_fallido" if columna_hash == "password_hash" else "pin_fallido")
            conn.commit()
            raise ErrorAcceso(mensaje)

        cur.execute(
            "UPDATE usuarios SET intentos_fallidos = 0, bloqueado_hasta = NULL, "
            "ultimo_acceso = %s WHERE id = %s",
            (ahora, fila["id"]),
        )
        registrar_auditoria(cur, fila["id"], "login" if columna_hash == "password_hash" else "pin_ok")
        conn.commit()
        return {
            "id": fila["id"],
            "usuario": fila["usuario"],
            "rol": fila["rol"],
            "empleado_id": fila["empleado_id"],
            "debe_cambiar_password": bool(fila["debe_cambiar_password"]),
        }
    finally:
        cur.close()


def iniciar_sesion(conn, usuario: str, password: str, ahora: datetime | None = None) -> dict:
    """Valida usuario y contraseña. Devuelve {'id','usuario','rol','empleado_id','debe_cambiar_password'}."""
    return _autenticar(conn, "u.usuario = %s", usuario.strip(), password, "password_hash",
                       "Usuario o contraseña incorrectos.", ahora)


def validar_pin(pin: str) -> list[str]:
    """Devuelve los problemas del PIN (4 a 6 dígitos, sin repeticiones ni secuencias obvias)."""
    if not (pin.isascii() and pin.isdigit()):
        return ["El PIN debe tener solo números."]
    if not LONGITUD_PIN[0] <= len(pin) <= LONGITUD_PIN[1]:
        return [f"El PIN debe tener de {LONGITUD_PIN[0]} a {LONGITUD_PIN[1]} dígitos."]
    if len(set(pin)) == 1:
        return ["No uses un solo número repetido."]
    if pin in "0123456789" or pin in "9876543210":
        return ["No uses una secuencia como 1234."]
    return []


def autenticar_pin(conn, usuario_id: int, pin: str, ahora: datetime | None = None) -> dict:
    """Identifica a un empleado en el mostrador con su PIN. Solo cuentas con rol 'empleado'."""
    return _autenticar(conn, "u.id = %s", usuario_id, pin, "pin_hash", "Empleado o PIN incorrectos.", ahora,
                       solo_empleado=True)


def crear_usuario(conn, usuario: str, password: str, rol: str, empleado_id: int | None = None) -> int:
    problemas = validar_politica(password)
    if problemas:
        raise ValueError(" ".join(problemas))
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM roles WHERE nombre = %s", (rol,))
        fila = cur.fetchone()
        if not fila:
            raise ValueError(f"Rol desconocido: {rol}")
        cur.execute(
            "INSERT INTO usuarios (rol_id, empleado_id, usuario, password_hash) "
            "VALUES (%s, %s, %s, %s)",
            (fila[0], empleado_id, usuario.strip(), hashear(password)),
        )
        nuevo_id = cur.lastrowid
        conn.commit()
        return nuevo_id
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def requiere_rol(sesion: dict, *roles: str) -> None:
    """Lanza ErrorAcceso si la sesión no tiene alguno de los roles dados."""
    if sesion.get("rol") not in roles:
        raise ErrorAcceso("No tienes permiso para esta acción.")
