"""Instalación inicial: crea la base, un usuario MySQL limitado, el esquema y
el primer administrador. Se ejecuta una sola vez en la PC del local:

    python -m oceanica.init_db

La contraseña de root de MySQL solo se usa durante esta ejecución y no se guarda.
"""
from __future__ import annotations

import getpass
import re
import secrets
import sys

import mysql.connector

from .config import RUTA_CONFIG, ConfigDB, cargar_config, guardar_config
from .db import aplicar_migraciones, conectar
from .seguridad import crear_usuario, validar_politica

_IDENT = re.compile(r"^[A-Za-z0-9_]{1,32}$")


def _pedir_password_admin() -> str:
    while True:
        p1 = getpass.getpass("Contraseña para el administrador: ")
        problemas = validar_politica(p1)
        if problemas:
            print(" ".join(problemas))
            continue
        if p1 != getpass.getpass("Repite la contraseña: "):
            print("No coinciden, intenta de nuevo.")
            continue
        return p1


def _ya_configurado() -> bool:
    """True si hay una configuración que ya conecta: no hace falta root."""
    if not RUTA_CONFIG.exists():
        return False
    try:
        conectar(cargar_config()).close()
        return True
    except Exception:
        return False


def main() -> int:
    print("== Oceánica Gestión: instalación de la base de datos ==")
    if _ya_configurado():
        conn = conectar(cargar_config())
        print("Ya existe una configuración que funciona (", RUTA_CONFIG, "). No se necesita root.", sep="")
        print("Migraciones aplicadas:", aplicar_migraciones(conn) or "ninguna (ya estaba al día)")
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM usuarios")
        if cur.fetchone()[0] == 0:
            crear_usuario(conn, input("Nombre de usuario del administrador [admin]: ").strip() or "admin",
                          _pedir_password_admin(), "administrador")
            print("Administrador creado.")
        conn.close()
        return 0
    host = input("Servidor MySQL [127.0.0.1]: ").strip() or "127.0.0.1"
    base = input("Nombre de la base [oceanica]: ").strip() or "oceanica"
    usuario_app = input("Usuario MySQL del sistema [oceanica_app]: ").strip() or "oceanica_app"
    if usuario_app.lower() == "root":
        print("El sistema no debe usar root. Usa el usuario sugerido (oceanica_app).")
        return 1
    if not (_IDENT.match(base) and _IDENT.match(usuario_app)):
        print("Los nombres solo pueden llevar letras, números y guion bajo.")
        return 1
    root_pass = getpass.getpass("Contraseña de root de MySQL (no se guarda): ")

    try:
        admin = mysql.connector.connect(host=host, user="root", password=root_pass)
    except mysql.connector.Error as e:
        print("No se pudo conectar como root:", e.msg)
        return 1

    pass_app = secrets.token_urlsafe(24)
    cur = admin.cursor()
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{base}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    cur.execute(f"CREATE USER IF NOT EXISTS '{usuario_app}'@'localhost' IDENTIFIED BY %s", (pass_app,))
    cur.execute(f"ALTER USER '{usuario_app}'@'localhost' IDENTIFIED BY %s", (pass_app,))
    # Permisos solo sobre esta base: el sistema nunca usa root.
    cur.execute(f"GRANT ALL PRIVILEGES ON `{base}`.* TO '{usuario_app}'@'localhost'")
    cur.execute("FLUSH PRIVILEGES")
    cur.close()
    admin.close()

    cfg = ConfigDB(host=host, usuario=usuario_app, password=pass_app, base=base)
    ruta = guardar_config(cfg)
    print("Configuración guardada en", ruta)

    conn = conectar(cfg)
    aplicadas = aplicar_migraciones(conn)
    print("Migraciones aplicadas:", aplicadas or "ninguna (ya estaba al día)")

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM usuarios")
    if cur.fetchone()[0] == 0:
        nombre = input("Nombre de usuario del administrador [admin]: ").strip() or "admin"
        crear_usuario(conn, nombre, _pedir_password_admin(), "administrador")
        print("Administrador creado.")
    conn.close()
    print("Listo. Guarda la contraseña del administrador en un lugar seguro.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
