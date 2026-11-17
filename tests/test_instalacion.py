"""Instalador: el usuario del sistema debe poder entrar por TCP a 127.0.0.1 aunque el servidor tenga
`skip-name-resolve` (ahí un usuario creado solo como @'localhost' recibe «Access denied»).

Necesita root del servidor DESECHABLE de pruebas: OCEANICA_TEST_ROOT_PASSWORD. Sin esa variable se omite."""
import os

import mysql.connector
import pytest

from oceanica import init_db

ROOT = os.environ.get("OCEANICA_TEST_ROOT_PASSWORD")
HOST = os.environ.get("OCEANICA_TEST_DB_HOST", "127.0.0.1")
PORT = int(os.environ.get("OCEANICA_TEST_DB_PORT", "3306"))
BASE, USUARIO = "oceanica_instalador_prueba", "oc_inst_prueba"


def test_nombres_invalidos_no_llegan_al_sql():
    class SinUso:
        def execute(self, *a):
            pytest.fail("no debe ejecutar nada con un nombre inválido")
    for base, usuario in (("oceanica; DROP DATABASE x", "app"), ("oceanica", "app'@'%"), ("", "app")):
        with pytest.raises(ValueError):
            init_db.crear_base_y_usuario(SinUso(), base, usuario, "x")


@pytest.mark.skipif(not ROOT, reason="falta OCEANICA_TEST_ROOT_PASSWORD (root del servidor de pruebas)")
def test_usuario_del_sistema_cubre_las_tres_formas_locales_y_nada_mas():
    root = mysql.connector.connect(host=HOST, port=PORT, user="root", password=ROOT)
    cur = root.cursor()
    try:
        init_db.crear_base_y_usuario(cur, BASE, USUARIO, "Clave#Primera1")
        init_db.crear_base_y_usuario(cur, BASE, USUARIO, "Clave#Segunda2")     # repetir la instalación no falla
        cur.execute("SELECT host FROM mysql.user WHERE user = %s ORDER BY host", (USUARIO,))
        assert [h for (h,) in cur.fetchall()] == ["127.0.0.1", "::1", "localhost"]   # nunca '%': sin acceso por red
        for host in init_db.HOSTS_LOCALES:
            cur.execute(f"SHOW GRANTS FOR '{USUARIO}'@'{host}'")
            permisos = " ".join(g for (g,) in cur.fetchall())
            assert f"`{BASE}`.*" in permisos and "ON *.* TO" in permisos and "ALL PRIVILEGES ON *.*" not in permisos
            # 10.3 guarda la contraseña en `Password`; 10.4+ en `authentication_string`
            cur.execute("SELECT 1 FROM mysql.user WHERE user = %s AND host = %s "
                        "AND PASSWORD(%s) IN (Password, authentication_string)", (USUARIO, host, "Clave#Segunda2"))
            assert cur.fetchone(), f"la contraseña nueva no quedó en @{host}"
    finally:
        for host in init_db.HOSTS_LOCALES:
            cur.execute(f"DROP USER IF EXISTS '{USUARIO}'@'{host}'")
        cur.execute(f"DROP DATABASE IF EXISTS `{BASE}`")
        cur.close()
        root.close()
