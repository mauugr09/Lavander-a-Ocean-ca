"""Primera instalación sin consola: la usa el asistente que aparece al abrir el programa por primera vez.

Dos casos:
- **Servidor recién instalado por nuestro instalador**: root no tiene contraseña. El asistente le pone la
  «contraseña de recuperación» que elige la encargada (solo hace falta para restablecer su cuenta) y crea todo.
- **Servidor que ya existía** (por ejemplo, la MariaDB 10.3.9 del local): pide la contraseña de root actual.

En los dos casos: crea la base y el usuario limitado `oceanica_app` (con una contraseña aleatoria que solo conoce
config.ini) y aplica las migraciones. La cuenta de la encargada que se escribe en el asistente **siempre queda
funcionando**: si no existe se crea; si ya existía (una base de una instalación anterior) se le pone la contraseña
nueva y se desbloquea. Quien tiene la contraseña de root ya manda sobre la base, así que no se abre ningún permiso
nuevo. La contraseña de root no se guarda en ningún lado.
"""
from __future__ import annotations

import logging
import re
import secrets

import mysql.connector

from .config import ConfigDB, guardar_config
from .db import aplicar_migraciones, conectar
from .init_db import crear_base_y_usuario
from .seguridad import crear_usuario, hashear, registrar_auditoria, validar_politica

log = logging.getLogger("oceanica")

HOST, PUERTO, BASE, USUARIO_APP = "127.0.0.1", 3306, "oceanica", "oceanica_app"
_USUARIO = re.compile(r"^[A-Za-z0-9_.-]{3,40}$")

SIN_SERVIDOR, ROOT_SIN_CONTRASENA, ROOT_CON_CONTRASENA = "sin_servidor", "root_sin_contrasena", "root_con_contrasena"


class ErrorInstalacion(Exception):
    """Mensaje listo para mostrar a quien instala (sin texto técnico)."""


def _conectar_root(host: str, puerto: int, usuario_root: str, password: str):
    return mysql.connector.connect(host=host, port=puerto, user=usuario_root, password=password, connection_timeout=5)


def estado_servidor(host: str = HOST, puerto: int = PUERTO, usuario_root: str = "root") -> str:
    """¿Hay servidor? ¿root todavía no tiene contraseña (instalación nueva)?"""
    try:
        _conectar_root(host, puerto, usuario_root, "").close()
        return ROOT_SIN_CONTRASENA
    except mysql.connector.Error as e:
        # 1045: acceso denegado (sí hay servidor y root tiene contraseña); 1698: root solo por socket (Linux)
        if getattr(e, "errno", None) in (1045, 1698):
            return ROOT_CON_CONTRASENA
        log.info("Sin servidor de base de datos en %s:%s (%s)", host, puerto, getattr(e, "errno", e))
        return SIN_SERVIDOR


def _poner_contrasena_root(cur, usuario_root: str, nueva: str) -> None:
    """Todas las cuentas de root quedan con la contraseña nueva: ninguna se queda sin contraseña."""
    if not re.fullmatch(r"[A-Za-z0-9_]+", usuario_root):
        raise ErrorInstalacion("Nombre de administrador de la base no válido.")
    cur.execute("SELECT host FROM mysql.user WHERE user = %s", (usuario_root,))
    for (h,) in cur.fetchall():
        h = h.decode() if isinstance(h, (bytes, bytearray)) else h
        if "'" in h or "\\" in h:   # el host viene de mysql.user, no del teclado; aun así no se arma SQL raro
            continue
        cur.execute(f"ALTER USER '{usuario_root}'@'{h}' IDENTIFIED BY %s", (nueva,))
    cur.execute("FLUSH PRIVILEGES")


def instalar(*, root_actual: str, nueva_root: str | None, usuario_admin: str, password_admin: str,
             host: str = HOST, puerto: int = PUERTO, base: str = BASE, usuario_app: str = USUARIO_APP,
             usuario_root: str = "root", guardar: bool = True) -> dict:
    """Deja el sistema listo. Devuelve {'cfg', 'admin_creado'}. Lanza ErrorInstalacion con un mensaje claro."""
    if nueva_root is not None:
        problemas = validar_politica(nueva_root)
        if problemas:
            raise ErrorInstalacion("Contraseña de recuperación: " + " ".join(problemas))
    usuario_admin = (usuario_admin or "").strip()
    if not _USUARIO.match(usuario_admin):
        raise ErrorInstalacion("El usuario de la encargada debe tener de 3 a 40 letras o números, sin espacios.")
    problemas = validar_politica(password_admin or "")
    if problemas:
        raise ErrorInstalacion("Contraseña de la encargada: " + " ".join(problemas))
    if nueva_root is not None and nueva_root == password_admin:
        raise ErrorInstalacion("La contraseña de recuperación debe ser distinta a la de la encargada.")

    try:
        raiz = _conectar_root(host, puerto, usuario_root, root_actual)
    except mysql.connector.Error as e:
        log.warning("No se pudo entrar como %s: %s", usuario_root, getattr(e, "errno", e))
        if getattr(e, "errno", None) in (1045, 1698):
            raise ErrorInstalacion("La contraseña de la base de datos (root) no es correcta.") from None
        raise ErrorInstalacion("No se encontró la base de datos en esta computadora. "
                               "Vuelva a ejecutar el instalador de Oceánica.") from None
    pass_app = secrets.token_urlsafe(24)
    try:
        cur = raiz.cursor()
        crear_base_y_usuario(cur, base, usuario_app, pass_app)
        if nueva_root is not None:
            _poner_contrasena_root(cur, usuario_root, nueva_root)
        cur.close()
    finally:
        raiz.close()

    cfg = ConfigDB(host=host, port=puerto, usuario=usuario_app, password=pass_app, base=base)
    conn = conectar(cfg)
    try:
        aplicar_migraciones(conn)
        cuenta = _dejar_lista_la_encargada(conn, usuario_admin, password_admin)
    finally:
        conn.close()
    if guardar:
        guardar_config(cfg)
    return {"cfg": cfg, "cuenta": cuenta, "admin_creado": cuenta == "creada"}


def _dejar_lista_la_encargada(conn, usuario: str, password: str) -> str:
    """Devuelve 'creada' o 'restablecida'. Una cuenta de empleado con ese nombre no se toca."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT u.id, r.nombre FROM usuarios u JOIN roles r ON r.id = u.rol_id WHERE u.usuario = %s",
                    (usuario,))
        fila = cur.fetchone()
    finally:
        cur.close()
    if not fila:
        crear_usuario(conn, usuario, password, "administrador")
        return "creada"
    if fila[1] != "administrador":
        raise ErrorInstalacion(f"«{usuario}» ya es la cuenta de un empleado. Elija otro usuario para la encargada.")
    cur = conn.cursor()
    try:
        cur.execute("UPDATE usuarios SET password_hash = %s, activo = 1, intentos_fallidos = 0, bloqueado_hasta = NULL, "
                    "debe_cambiar_password = 0 WHERE id = %s", (hashear(password), fila[0]))
        registrar_auditoria(cur, fila[0], "password_restablecido_instalacion", "usuarios", fila[0],
                            "Desde el asistente de instalación (con la contraseña de root)")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return "restablecida"
