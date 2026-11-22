"""Actualizar (migrar) con respaldo previo: el instalador corre `migrar` en cada versión nueva, y una migración que
falla a la mitad no se deshace sola. Estas pruebas rehacen la base de pruebas y la dejan completa al terminar."""
import shutil

import pytest

from oceanica import migrar, respaldos
from oceanica.config import CARPETA_MIGRACIONES
from oceanica.db import aplicar_migraciones, listar_migraciones, migraciones_pendientes

from .conftest import _CFG, _vaciar_todo
from .test_app import qapp  # noqa: F401  (fixture de Qt)

pytestmark = pytest.mark.skipif(not (shutil.which("mysqldump") and shutil.which("mysql")),
                                reason="faltan mysqldump/mysql en el PATH")
ULTIMA = max(v for v, _, _ in listar_migraciones())


@pytest.fixture()
def base_vieja(_base, tmp_path):
    """La base del cliente una versión atrás (sin la última migración) y con un cliente capturado."""
    conn = _base
    vieja = tmp_path / "migraciones_viejas"
    vieja.mkdir()
    for v, _, ruta in listar_migraciones():
        if v < ULTIMA:
            shutil.copy(ruta, vieja / ruta.name)
    _vaciar_todo(conn)
    aplicar_migraciones(conn, vieja)
    cur = conn.cursor()
    cur.execute("INSERT INTO clientes (nombre, telefono) VALUES ('Clienta de antes', '5550001111')")
    conn.commit()
    cur.close()
    yield conn
    aplicar_migraciones(conn, CARPETA_MIGRACIONES)  # pase lo que pase, la base queda completa para las demás pruebas


def _version(conn):
    cur = conn.cursor()
    cur.execute("SELECT MAX(version) FROM schema_migraciones")
    v = cur.fetchone()[0]
    cur.close()
    conn.commit()
    return v


def test_respalda_antes_de_actualizar_y_el_respaldo_regresa_a_la_version_anterior(base_vieja, tmp_path):
    conn = base_vieja
    assert migraciones_pendientes(conn) == ([ULTIMA], True)
    r = migrar.actualizar(_CFG, carpeta_respaldos=tmp_path / "respaldos")
    assert r["aplicadas"] == [ULTIMA] and r["respaldo"].exists()
    assert r["respaldo"].name.endswith("_automatico.sql.gz")
    assert _version(conn) == ULTIMA

    respaldos.restaurar(r["respaldo"], cfg=_CFG)                    # el respaldo es de ANTES de actualizar
    assert _version(conn) == ULTIMA - 1
    cur = conn.cursor()
    cur.execute("SELECT nombre FROM clientes")
    assert cur.fetchall() == [("Clienta de antes",)]
    cur.close()
    conn.commit()


def test_si_el_respaldo_falla_no_se_toca_la_base(base_vieja, tmp_path, monkeypatch):
    def sin_mysqldump(programa):
        raise FileNotFoundError(f"No se encontró '{programa}'.")
    monkeypatch.setattr(respaldos, "_buscar", sin_mysqldump)
    with pytest.raises(migrar.ErrorActualizacion, match="No se cambió nada"):
        migrar.actualizar(_CFG, carpeta_respaldos=tmp_path / "respaldos")
    assert _version(base_vieja) == ULTIMA - 1
    # con --sin-respaldo (decisión explícita de quien actualiza) sí avanza
    assert migrar.actualizar(_CFG, carpeta_respaldos=tmp_path / "r", sin_respaldo=True)["aplicadas"] == [ULTIMA]


def test_si_una_migracion_falla_dice_como_volver_con_el_respaldo(base_vieja, tmp_path):
    rota = tmp_path / "migraciones_con_error"
    shutil.copytree(CARPETA_MIGRACIONES, rota)
    (rota / f"{ULTIMA + 1:03d}_rota.sql").write_text("ALTER TABLE no_existe ADD COLUMN x INT;", encoding="utf-8")
    with pytest.raises(migrar.ErrorActualizacion) as e:
        migrar.actualizar(_CFG, carpeta=rota, carpeta_respaldos=tmp_path / "respaldos")
    respaldo = next((tmp_path / "respaldos").glob("*_automatico.sql.gz"))
    assert "--restaurar" in str(e.value) and str(respaldo) in str(e.value)


def test_al_dia_o_instalacion_nueva_no_hace_respaldo(_base, tmp_path, monkeypatch):
    monkeypatch.setattr(respaldos, "crear_respaldo", lambda *a, **k: pytest.fail("no debe respaldar"))
    _vaciar_todo(_base)                                              # instalación nueva: no hay datos que proteger
    try:
        assert migraciones_pendientes(_base)[1] is False
        r = migrar.actualizar(_CFG, carpeta_respaldos=tmp_path)
        assert r["aplicadas"][-1] == ULTIMA and r["respaldo"] is None
        assert migrar.actualizar(_CFG, carpeta_respaldos=tmp_path) == {"aplicadas": [], "respaldo": None}
    finally:
        aplicar_migraciones(_base, CARPETA_MIGRACIONES)


def test_main_informa_y_devuelve_codigo_de_error(base_vieja, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(migrar, "cargar_config", lambda: _CFG)
    monkeypatch.setattr(migrar, "CARPETA_RESPALDOS", tmp_path)
    monkeypatch.setattr(migrar.actualizar, "__defaults__", (CARPETA_MIGRACIONES, tmp_path, False))
    assert migrar.main([]) == 0
    salida = capsys.readouterr().out
    assert "Respaldo previo:" in salida and str(ULTIMA) in salida
    assert migrar.main([]) == 0 and "ya estaba al día" in capsys.readouterr().out


# ---------- el programa se actualiza solo al abrir (nadie corre «migrar») -----------------

def _abrir(monkeypatch, tmp_path):
    """Corre aplicacion.main() contra la base de pruebas sin mostrar ventanas. Devuelve los avisos críticos."""
    from PySide6.QtWidgets import QMessageBox
    from oceanica.app import aplicacion
    avisos = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: avisos.append(a[2]))
    monkeypatch.setattr(aplicacion, "_configurar_log", lambda: None)
    monkeypatch.setattr(aplicacion, "cargar_config", lambda: _CFG)
    monkeypatch.setattr(aplicacion, "RUTA_CONFIG", tmp_path)                # «ya instalado»
    monkeypatch.setattr(aplicacion.Ventana, "showMaximized", lambda self: None)
    monkeypatch.setattr(type(aplicacion.preparar_aplicacion()), "exec", lambda self: 0)
    monkeypatch.setattr(migrar.actualizar, "__defaults__", (CARPETA_MIGRACIONES, tmp_path / "respaldos", False))
    return aplicacion, avisos


def test_al_abrir_se_actualiza_solo_con_respaldo(qapp, base_vieja, tmp_path, monkeypatch):
    aplicacion, avisos = _abrir(monkeypatch, tmp_path)
    assert aplicacion.main() == 0 and avisos == []
    assert _version(base_vieja) == ULTIMA                                  # se aplicó sin correr «migrar»
    assert len(list((tmp_path / "respaldos").glob("*_automatico.sql.gz"))) == 1
    assert aplicacion.main() == 0                                          # la segunda vez no hay nada que hacer
    assert len(list((tmp_path / "respaldos").glob("*_automatico.sql.gz"))) == 1


def test_si_no_se_puede_actualizar_no_abre_y_avisa_sin_texto_tecnico(qapp, base_vieja, tmp_path, monkeypatch):
    aplicacion, avisos = _abrir(monkeypatch, tmp_path)
    monkeypatch.setattr(aplicacion.Ventana, "__init__", lambda *a, **k: pytest.fail("no debe abrir la ventana"))

    def sin_mysqldump(programa):
        raise FileNotFoundError(f"No se encontró '{programa}'. Agrega la carpeta bin de MySQL al PATH de Windows.")
    monkeypatch.setattr(respaldos, "_buscar", sin_mysqldump)
    assert aplicacion.main() == 1
    assert _version(base_vieja) == ULTIMA - 1                              # no se tocó la base
    aviso = avisos[-1]
    assert "encargada" in aviso and "papel" in aviso
    assert not any(t in aviso for t in ("mysqldump", "PATH", "migrar", "python", "--"))
