"""Fixtures de las pruebas de integración.

Requieren un servidor MySQL o MariaDB con una base DESECHABLE (se borra y recrea
en cada sesión de pruebas). Se configura con variables de entorno:
OCEANICA_TEST_DB_HOST, _PORT, _USER, _PASSWORD, _NAME. Si no hay servidor
disponible, las pruebas de integración se omiten.
"""
import os

import mysql.connector
import pytest

from oceanica import seguridad
from oceanica.config import ConfigDB
from oceanica.db import aplicar_migraciones, conectar

seguridad.BCRYPT_ROUNDS = 4  # contraseñas rápidas solo en pruebas

_CFG = ConfigDB(
    host=os.environ.get("OCEANICA_TEST_DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("OCEANICA_TEST_DB_PORT", "3306")),
    usuario=os.environ.get("OCEANICA_TEST_DB_USER", "oc_test"),
    password=os.environ.get("OCEANICA_TEST_DB_PASSWORD", "oc_test_pw"),
    base=os.environ.get("OCEANICA_TEST_DB_NAME", "oceanica_test"),
)
_CATALOGOS = {"roles", "metodos_pago", "categorias_servicio", "categorias_insumo", "conceptos_nomina",
              "configuracion", "schema_migraciones"}


def _vaciar_todo(conn):
    cur = conn.cursor()
    cur.execute("SET FOREIGN_KEY_CHECKS = 0")
    cur.execute("SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = DATABASE()")
    for nombre, tipo in cur.fetchall():
        cur.execute(f"DROP {'VIEW' if tipo == 'VIEW' else 'TABLE'} IF EXISTS `{nombre}`")
    cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    conn.commit()
    cur.close()


@pytest.fixture(scope="session")
def _base():
    try:
        conn = conectar(_CFG)
    except mysql.connector.Error as e:
        pytest.skip(f"No hay servidor MySQL/MariaDB de pruebas: {e}")
    _vaciar_todo(conn)
    aplicar_migraciones(conn)
    yield conn
    conn.close()


@pytest.fixture()
def conn(_base):
    """Conexión con los datos de negocio vacíos (los catálogos se conservan)."""
    c = _base
    cur = c.cursor()
    cur.execute("SET FOREIGN_KEY_CHECKS = 0")
    cur.execute("SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'")
    for (t,) in cur.fetchall():
        if t not in _CATALOGOS:
            cur.execute(f"TRUNCATE TABLE `{t}`")
    cur.execute("DELETE FROM categorias_servicio")
    cur.execute("DELETE FROM categorias_insumo")
    cur.execute("INSERT INTO categorias_servicio (nombre) VALUES ('Lavado por kilo'),('Planchado')")
    cur.execute("INSERT INTO categorias_insumo (nombre) VALUES ('Detergentes'),('Empaque')")
    cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    c.commit()
    cur.close()
    return c


def _sesion(conn, usuario, rol):
    cur = conn.cursor()
    cur.execute("SELECT id FROM roles WHERE nombre = %s", (rol,))
    rol_id = cur.fetchone()[0]
    cur.execute("INSERT INTO usuarios (rol_id, usuario, password_hash) VALUES (%s,%s,%s)",
                (rol_id, usuario, seguridad.hashear("Clave#Prueba1")))
    uid = cur.lastrowid
    conn.commit()
    cur.close()
    return {"id": uid, "usuario": usuario, "rol": rol}


@pytest.fixture()
def admin(conn):
    return _sesion(conn, "admin", "administrador")


@pytest.fixture()
def empleado(conn, admin):
    return _sesion(conn, "cajero", "empleado")
