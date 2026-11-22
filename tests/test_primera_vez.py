"""Primera instalación sin consola (asistente al abrir el programa).

Las pruebas con servidor usan un administrador DESECHABLE creado para la prueba (no tocan la contraseña de root del
servidor de pruebas). Necesitan OCEANICA_TEST_ROOT_PASSWORD; sin ella se omiten."""
import os

import mysql.connector
import pytest

from oceanica import instalacion
from oceanica.db import conectar

ROOT = os.environ.get("OCEANICA_TEST_ROOT_PASSWORD")
HOST = os.environ.get("OCEANICA_TEST_DB_HOST", "127.0.0.1")
PORT = int(os.environ.get("OCEANICA_TEST_DB_PORT", "3306"))
BASE, APP, RAIZ = "oceanica_primera_vez", "oc_pv_app", "oc_pv_raiz"
HOSTS_RAIZ = ("%", "localhost", "127.0.0.1")
requiere_root = pytest.mark.skipif(not ROOT, reason="falta OCEANICA_TEST_ROOT_PASSWORD (root del servidor de pruebas)")

DATOS = dict(usuario_admin="encargada", password_admin="Encargada#2026", host=HOST, puerto=PORT, base=BASE,
             usuario_app=APP, usuario_root=RAIZ, guardar=False)


def _root():
    return mysql.connector.connect(host=HOST, port=PORT, user="root", password=ROOT)


@pytest.fixture()
def servidor_nuevo():
    """Simula un servidor recién instalado: un administrador con todos los permisos y SIN contraseña."""
    r = _root()
    cur = r.cursor()

    def limpiar():
        for h in HOSTS_RAIZ:
            cur.execute(f"DROP USER IF EXISTS '{RAIZ}'@'{h}'")
        for h in ("localhost", "127.0.0.1", "::1"):
            cur.execute(f"DROP USER IF EXISTS '{APP}'@'{h}'")
        cur.execute(f"DROP DATABASE IF EXISTS `{BASE}`")
    limpiar()
    for h in HOSTS_RAIZ:
        cur.execute(f"CREATE USER '{RAIZ}'@'{h}' IDENTIFIED BY ''")
        cur.execute(f"GRANT ALL PRIVILEGES ON *.* TO '{RAIZ}'@'{h}' WITH GRANT OPTION")
    cur.execute("FLUSH PRIVILEGES")
    yield
    limpiar()
    cur.close()
    r.close()


def test_validaciones_antes_de_tocar_el_servidor():
    sin_servidor = dict(DATOS, puerto=1)    # si llegara a conectar fallaría distinto: aquí no debe ni intentarlo
    casos = [
        (dict(nueva_root="corta"), "recuperación"),
        (dict(nueva_root="Recupera#2026", usuario_admin="a b"), "usuario de la encargada"),
        (dict(nueva_root="Recupera#2026", password_admin="123456789"), "encargada"),
        (dict(nueva_root="Encargada#2026"), "distinta"),
    ]
    for cambios, texto in casos:
        with pytest.raises(instalacion.ErrorInstalacion, match=texto):
            instalacion.instalar(**{**sin_servidor, "root_actual": "", **cambios})


def test_sin_servidor():
    assert instalacion.estado_servidor(HOST, 1) == instalacion.SIN_SERVIDOR
    with pytest.raises(instalacion.ErrorInstalacion, match="No se encontró la base de datos"):
        instalacion.instalar(**{**DATOS, "puerto": 1, "root_actual": "", "nueva_root": "Recupera#2026"})


@requiere_root
def test_servidor_nuevo_queda_con_contrasena_y_listo_para_entrar(servidor_nuevo):
    assert instalacion.estado_servidor(HOST, PORT, RAIZ) == instalacion.ROOT_SIN_CONTRASENA
    r = instalacion.instalar(root_actual="", nueva_root="Recupera#2026", **DATOS)
    assert r["admin_creado"]

    # ninguna cuenta del administrador de la base se quedó sin contraseña
    assert instalacion.estado_servidor(HOST, PORT, RAIZ) == instalacion.ROOT_CON_CONTRASENA
    mysql.connector.connect(host=HOST, port=PORT, user=RAIZ, password="Recupera#2026").close()

    # el sistema entra con su usuario limitado, el esquema está al día y la encargada existe
    conn = conectar(r["cfg"])
    cur = conn.cursor()
    cur.execute("SELECT u.usuario, r.nombre FROM usuarios u JOIN roles r ON r.id = u.rol_id")
    assert cur.fetchall() == [("encargada", "administrador")]
    assert r["cfg"].usuario == APP and r["cfg"].password and r["cfg"].password != "Recupera#2026"
    conn.close()


@requiere_root
def test_volver_a_instalar_conserva_a_la_encargada(servidor_nuevo):
    primera = instalacion.instalar(root_actual="", nueva_root="Recupera#2026", **DATOS)
    with pytest.raises(instalacion.ErrorInstalacion, match="no es correcta"):
        instalacion.instalar(root_actual="otra", nueva_root=None, **DATOS)
    segunda = instalacion.instalar(root_actual="Recupera#2026", nueva_root=None,
                                   **{**DATOS, "usuario_admin": "otra", "password_admin": "OtraClave#1"})
    assert not segunda["admin_creado"]
    assert segunda["cfg"].password != primera["cfg"].password       # la clave del sistema se renueva
    with pytest.raises(mysql.connector.Error):
        conectar(primera["cfg"])
    conn = conectar(segunda["cfg"])
    cur = conn.cursor()
    cur.execute("SELECT usuario FROM usuarios")
    assert cur.fetchall() == [("encargada",)]
    conn.close()


# ---------- la pantalla del asistente (Qt sin ventana) -------------------------------

@pytest.fixture()
def qt(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QMessageBox
    from oceanica.app.aplicacion import preparar_aplicacion
    preparar_aplicacion()
    avisos = []
    for tipo in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, tipo, lambda *a, _t=tipo, **k: avisos.append((_t, a[2])))
    return avisos


def _visible(dlg, campo) -> bool:
    return dlg.form.isRowVisible(campo)


def test_asistente_sin_servidor_ofrece_reintentar(qt, monkeypatch):
    from oceanica.app.asistente import AsistenteInstalacion
    monkeypatch.setattr(instalacion, "estado_servidor", lambda *a, **k: instalacion.SIN_SERVIDOR)
    dlg = AsistenteInstalacion()
    assert dlg.b_instalar.isHidden() and not dlg.b_reintentar.isHidden()
    assert not _visible(dlg, dlg.clave) and "No se encontró" in dlg.aviso.text()
    monkeypatch.setattr(instalacion, "estado_servidor", lambda *a, **k: instalacion.ROOT_CON_CONTRASENA)
    dlg.b_reintentar.click()
    assert not dlg.b_instalar.isHidden() and _visible(dlg, dlg.root_actual) and not _visible(dlg, dlg.recuperacion)


@requiere_root
def test_asistente_instala_de_punta_a_punta(qt, servidor_nuevo, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from oceanica.app.asistente import AsistenteInstalacion
    real_estado, real_instalar = instalacion.estado_servidor, instalacion.instalar
    monkeypatch.setattr(instalacion, "estado_servidor", lambda *a, **k: real_estado(HOST, PORT, RAIZ))
    extra = {k: v for k, v in DATOS.items() if k not in ("usuario_admin", "password_admin")}
    monkeypatch.setattr(instalacion, "instalar", lambda **k: real_instalar(**{**k, **extra}))

    dlg = AsistenteInstalacion()
    assert _visible(dlg, dlg.recuperacion) and not _visible(dlg, dlg.root_actual)   # servidor nuevo
    dlg.usuario.setText("encargada")
    dlg.clave.setText("Encargada#2026")
    dlg.clave2.setText("Encargada#2026")
    dlg.recuperacion.setText("Recupera#2026")
    dlg.recuperacion2.setText("Recupera#202")                       # no coincide: no instala nada
    dlg.b_instalar.click()
    assert qt[-1] == ("warning", "Las contraseñas de recuperación no coinciden.") and dlg.resultado is None
    assert real_estado(HOST, PORT, RAIZ) == instalacion.ROOT_SIN_CONTRASENA

    dlg.recuperacion2.setText("Recupera#2026")
    dlg.b_instalar.click()
    assert qt[-1][0] == "information" and "encargada" in qt[-1][1]
    assert dlg.resultado["admin_creado"] and dlg.result() == QDialog.Accepted
    conectar(dlg.resultado["cfg"]).close()
