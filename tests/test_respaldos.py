"""Respaldo y restauración contra la base real: un respaldo que nunca se ha restaurado no es un respaldo.

Usan mysqldump y mysql (los mismos programas que usa el sistema); si no están en el PATH se omiten.
"""
import dataclasses
import gzip
import os
import shutil
import time
from decimal import Decimal

import pytest

from oceanica import respaldos
from oceanica.servicios import caja, clientes

from .conftest import _CFG

pytestmark = pytest.mark.skipif(not (shutil.which("mysqldump") and shutil.which("mysql")),
                                reason="faltan mysqldump/mysql en el PATH")


def _huella(conn) -> dict:
    """Suma de verificación de cada tabla (menos la bitácora de respaldos, que cambia al respaldar)."""
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE' AND table_name <> 'respaldos'")
    huella = {}
    for (tabla,) in cur.fetchall():
        cur.execute(f"CHECKSUM TABLE `{tabla}`")
        huella[tabla] = cur.fetchone()[1]
    cur.close()
    conn.commit()  # sin transacción abierta: la restauración necesita poder reemplazar las tablas
    return huella


def _config(conn, clave, valor):
    cur = conn.cursor()
    cur.execute("UPDATE configuracion SET valor = %s WHERE clave = %s", (valor, clave))
    assert cur.rowcount in (0, 1)
    conn.commit()
    cur.close()


@pytest.fixture()
def datos(conn, admin):
    """Un cliente con acentos y símbolos, una caja abierta y un movimiento: dinero y texto que no deben perderse."""
    cid = clientes.crear_cliente(conn, admin, "María José", "Ñúñez & Hnos.", "5511112222")
    caja.abrir_corte(conn, admin, Decimal("350.50"))
    caja.registrar_movimiento(conn, admin, "gasto", "Jabón «Roma» 5 kg", Decimal("89.90"))
    conn.commit()
    return cid


def test_restaurar_devuelve_la_base_exactamente_como_estaba(conn, admin, datos, tmp_path):
    antes = _huella(conn)
    archivo = respaldos.crear_respaldo("manual", admin["id"], cfg=_CFG, carpeta=tmp_path)
    assert archivo.exists() and archivo.name.endswith("_manual.sql.gz")
    with gzip.open(archivo, "rt", encoding="utf-8") as f:
        contenido = f.read()
    assert "CREATE TABLE `ordenes`" in contenido and "Ñúñez & Hnos." in contenido

    # después del respaldo se pierde un cliente y se altera el dinero de la caja
    cur = conn.cursor()
    cur.execute("DELETE FROM clientes WHERE id = %s", (datos,))
    cur.execute("UPDATE movimientos_caja SET monto = 1 WHERE concepto LIKE 'Jabón%'")
    conn.commit()
    cur.close()
    assert _huella(conn) != antes

    respaldos.restaurar(archivo, cfg=_CFG)
    assert _huella(conn) == antes
    c = clientes.obtener_cliente(conn, datos)
    assert (c["nombre"], c["apellidos"]) == ("María José", "Ñúñez & Hnos.")
    resumen = caja.resumen_corte(conn)
    assert resumen["gastos"] == Decimal("89.90")
    assert resumen["efectivo_esperado"] == Decimal("350.50") - Decimal("89.90")


def test_el_respaldo_queda_en_la_bitacora_y_se_copia_al_disco_externo(conn, admin, datos, tmp_path):
    externo = tmp_path / "usb"
    externo.mkdir()
    try:
        _config(conn, "respaldo_ruta_externa", str(externo))
        archivo = respaldos.crear_respaldo("automatico", None, cfg=_CFG, carpeta=tmp_path / "local")
        assert (externo / archivo.name).read_bytes() == archivo.read_bytes()

        # disco desconectado: el respaldo local se hace igual y queda anotado que no hubo copia
        _config(conn, "respaldo_ruta_externa", str(tmp_path / "no_existe"))
        time.sleep(1.1)  # el nombre del archivo lleva la hora al segundo
        sin_copia = respaldos.crear_respaldo("manual", admin["id"], cfg=_CFG, carpeta=tmp_path / "local")
        assert sin_copia.exists()
    finally:
        _config(conn, "respaldo_ruta_externa", "")
    cur = conn.cursor()
    cur.execute("SELECT archivo, tipo, usuario_id, copiado_a_externo, tamano_bytes FROM respaldos ORDER BY id")
    filas = cur.fetchall()
    cur.close()
    conn.commit()
    assert [(f[0], f[1], f[2], f[3]) for f in filas] == [(archivo.name, "automatico", None, 1),
                                                         (sin_copia.name, "manual", admin["id"], 0)]
    assert all(f[4] > 1000 for f in filas)


def test_se_borran_los_respaldos_mas_viejos_que_la_retencion(conn, admin, tmp_path):
    viejo = tmp_path / "oceanica_20260101_210000_automatico.sql.gz"
    reciente = tmp_path / "oceanica_20261110_210000_automatico.sql.gz"
    ajeno = tmp_path / "notas_del_dueño.txt"
    for f in (viejo, reciente, ajeno):
        f.write_bytes(b"x")
    hace = lambda dias: time.time() - dias * 86400  # noqa: E731
    os.utime(viejo, (hace(45), hace(45)))
    os.utime(reciente, (hace(5), hace(5)))
    os.utime(ajeno, (hace(400), hace(400)))
    nuevo = respaldos.crear_respaldo("manual", admin["id"], cfg=_CFG, carpeta=tmp_path)
    assert not viejo.exists()                       # retención por omisión: 30 días
    assert reciente.exists() and nuevo.exists()
    assert ajeno.exists()                           # nunca se borra lo que no es un respaldo del sistema


def test_si_el_respaldo_falla_no_queda_un_archivo_que_parezca_respaldo(conn, tmp_path):
    mala = dataclasses.replace(_CFG, password="contraseña-equivocada")
    with pytest.raises(RuntimeError, match="mysqldump falló"):
        respaldos.crear_respaldo("manual", None, cfg=mala, carpeta=tmp_path)
    assert list(tmp_path.glob("*.sql.gz")) == []


def test_restaurar_avisa_si_el_archivo_no_existe_o_no_sirve(conn, datos, tmp_path):
    antes = _huella(conn)
    with pytest.raises(FileNotFoundError):
        respaldos.restaurar(tmp_path / "no_hay.sql.gz", cfg=_CFG)
    roto = tmp_path / "roto.sql.gz"
    with gzip.open(roto, "wt", encoding="utf-8") as f:
        f.write("ESTO NO ES SQL;")
    with pytest.raises(RuntimeError, match="La restauración falló"):
        respaldos.restaurar(roto, cfg=_CFG)
    assert _huella(conn) == antes                   # un archivo inválido no toca los datos
