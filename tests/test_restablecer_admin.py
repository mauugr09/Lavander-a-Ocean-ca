"""Restablecer la contraseña de la única administradora cuando nadie puede entrar. Exige root del servidor de
pruebas DESECHABLE (OCEANICA_TEST_ROOT_PASSWORD); sin esa variable se omite."""
import os

import pytest

from oceanica import restablecer_admin, seguridad
from oceanica.seguridad import ErrorAcceso, iniciar_sesion

from .conftest import _CFG

ROOT = os.environ.get("OCEANICA_TEST_ROOT_PASSWORD")
pytestmark = pytest.mark.skipif(not ROOT, reason="falta OCEANICA_TEST_ROOT_PASSWORD (root del servidor de pruebas)")
TEMPORAL = "Temporal#2026x"


def _bloquear(conn, uid):
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET intentos_fallidos = 5, bloqueado_hasta = NOW() + INTERVAL 15 MINUTE, activo = 0 "
                "WHERE id = %s", (uid,))
    conn.commit()
    cur.close()


def test_la_unica_administradora_vuelve_a_entrar(conn, admin):
    _bloquear(conn, admin["id"])                                          # olvidó la clave y además quedó bloqueada
    with pytest.raises(ErrorAcceso):
        iniciar_sesion(conn, "admin", "Clave#Prueba1")
    assert [a["usuario"] for a in restablecer_admin.administradores(conn)] == ["admin"]

    restablecer_admin.restablecer(_CFG, ROOT, "admin", TEMPORAL)
    s = iniciar_sesion(conn, "admin", TEMPORAL)
    assert s["rol"] == "administrador" and s["debe_cambiar_password"]       # entra, pero debe cambiarla
    cur = conn.cursor()
    cur.execute("SELECT usuario_id, accion FROM auditoria WHERE registro_id = %s AND tabla = 'usuarios' "
                "ORDER BY id DESC LIMIT 1", (admin["id"],))
    assert cur.fetchone() == (None, "password_restablecida_root")
    cur.close()


def test_sin_root_correcto_o_con_datos_malos_no_cambia_nada(conn, admin, empleado):
    cur = conn.cursor()
    cur.execute("SELECT password_hash FROM usuarios WHERE id = %s", (admin["id"],))
    antes = cur.fetchone()[0]
    conn.commit()
    casos = [("no-es-root", "admin", TEMPORAL, "root no es correcta"),
             (ROOT, "admin", "corta", "caracteres"),                         # no cumple la política de contraseñas
             (ROOT, "nadie", TEMPORAL, "No existe un administrador"),
             (ROOT, "cajero", TEMPORAL, "No existe un administrador")]      # un empleado no se vuelve administrador
    for root, usuario, nueva, mensaje in casos:
        with pytest.raises(restablecer_admin.ErrorRestablecer, match=mensaje):
            restablecer_admin.restablecer(_CFG, root, usuario, nueva)
    cur.execute("SELECT password_hash FROM usuarios WHERE id = %s", (admin["id"],))
    assert cur.fetchone()[0] == antes and seguridad.verificar(  # sigue valiendo la contraseña de antes
        "Clave#Prueba1", antes)
    cur.close()
    conn.commit()


def test_el_comando_existe_en_el_ejecutable():
    from oceanica.__main__ import COMANDOS
    assert COMANDOS["restablecer-admin"] == "restablecer_admin"
