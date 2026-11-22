"""Restablece la contraseña de un administrador cuando nadie puede entrar (por ejemplo, la encargada la olvidó y es
la única administradora):

    python -m oceanica.restablecer_admin        (o OceanicaAdmin.exe restablecer-admin)

Pide la contraseña de root de MySQL/MariaDB: quien la conoce controla la base de todos modos, así que es la prueba
de que la persona tiene derecho a hacerlo. Root solo se usa para esa comprobación y no se guarda. La contraseña
nueva es temporal: el sistema obliga a cambiarla al entrar. Queda en la bitácora.
"""
from __future__ import annotations

import getpass
import sys

import mysql.connector

from .config import ConfigDB, cargar_config
from .db import conectar, transaccion
from .seguridad import hashear, registrar_auditoria, validar_politica


class ErrorRestablecer(Exception):
    """No se restableció nada; el mensaje dice por qué."""


def _comprobar_root(cfg: ConfigDB, root_password: str) -> None:
    try:
        mysql.connector.connect(host=cfg.host, port=cfg.port, user="root", password=root_password).close()
    except mysql.connector.Error as e:
        raise ErrorRestablecer("La contraseña de root no es correcta (o root no puede entrar desde esta computadora). "
                               "No se cambió nada.") from e


def administradores(conn) -> list[dict]:
    with transaccion(conn) as cur:
        cur.execute("SELECT u.id, u.usuario, u.activo, u.bloqueado_hasta FROM usuarios u JOIN roles r ON r.id = u.rol_id "
                    "WHERE r.nombre = 'administrador' ORDER BY u.usuario")
        return cur.fetchall()


def restablecer(cfg: ConfigDB, root_password: str, usuario: str, nueva: str) -> None:
    """Pone una contraseña temporal al administrador `usuario`, lo desbloquea y lo reactiva."""
    problemas = validar_politica(nueva)
    if problemas:
        raise ErrorRestablecer(" ".join(problemas))
    _comprobar_root(cfg, root_password)
    conn = conectar(cfg)
    try:
        with transaccion(conn) as cur:
            cur.execute("SELECT u.id FROM usuarios u JOIN roles r ON r.id = u.rol_id "
                        "WHERE u.usuario = %s AND r.nombre = 'administrador' FOR UPDATE", (usuario,))
            fila = cur.fetchone()
            if not fila:
                raise ErrorRestablecer(f"No existe un administrador llamado «{usuario}». No se cambió nada.")
            cur.execute("UPDATE usuarios SET password_hash = %s, debe_cambiar_password = 1, intentos_fallidos = 0, "
                        "bloqueado_hasta = NULL, activo = 1 WHERE id = %s", (hashear(nueva), fila["id"]))
            registrar_auditoria(cur, None, "password_restablecida_root", "usuarios", fila["id"],
                                f"{usuario}: restablecida con la contraseña de root")
    finally:
        conn.close()


def main() -> int:
    print("== Oceánica Gestión: restablecer la contraseña de un administrador ==")
    cfg = cargar_config()
    try:
        conn = conectar(cfg)
        admins = administradores(conn)
        conn.close()
    except mysql.connector.Error as e:
        print("No se pudo conectar a la base de datos:", getattr(e, "msg", e))
        return 1
    if not admins:
        print("No hay administradores. Use: python -m oceanica.init_db")
        return 1
    print("Administradores:", ", ".join(a["usuario"] + ("" if a["activo"] else " (desactivado)") for a in admins))
    usuario = input("¿A cuál le restablece la contraseña? ").strip()
    root_password = getpass.getpass("Contraseña de recuperación (root de la base; no se guarda): ")
    nueva = getpass.getpass("Contraseña temporal nueva: ")
    if getpass.getpass("Repítala: ") != nueva:
        print("Las contraseñas no coinciden. No se cambió nada.")
        return 1
    try:
        restablecer(cfg, root_password, usuario, nueva)
    except ErrorRestablecer as e:
        print(e)
        return 1
    print(f"Listo. «{usuario}» entra con la contraseña temporal y el sistema le pedirá cambiarla.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
