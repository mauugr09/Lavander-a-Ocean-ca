"""Sonidos, animaciones, pantalla de carga y entrada del administrador (Qt sin ventana)."""
import os
import wave

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtGui import QFocusEvent  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget  # noqa: E402

from oceanica.app import efectos as modulo  # noqa: E402
from oceanica.app.aplicacion import preparar_aplicacion  # noqa: E402
from oceanica.app.efectos import Efectos  # noqa: E402


@pytest.fixture()
def fx():
    app = preparar_aplicacion()
    app.removeEventFilter(modulo.efectos)   # el global que dejan instalado las pruebas de main(): aquí estorba
    e = Efectos()
    e.instalar(app)
    yield e
    app.removeEventFilter(e)


def test_los_tonos_se_generan_como_wav_validos(tmp_path):
    for nombre, (notas, vol) in modulo._SONIDOS.items():
        ruta = tmp_path / f"{nombre}.wav"
        modulo._generar(ruta, notas, vol)
        with wave.open(str(ruta)) as w:
            assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, modulo._FREC)
            assert 0 < w.getnframes() / w.getframerate() < 0.6          # cortos: es un mostrador


def test_sonidos_respetan_el_interruptor_y_no_se_enciman(fx):
    fx.reproducir("exito")
    fx.reproducir("clic")                       # justo después: no tapa al de éxito
    assert fx.historial == ["exito"]
    fx.configurar(sonidos=False, animaciones=True)
    fx.reproducir("error")
    assert fx.historial == ["exito"]
    fx.reproducir("inventado")                  # nombres desconocidos no truenan


def test_clic_en_boton_y_avisos_suenan(fx):
    w = QWidget()
    b = QPushButton("Cobrar", w)
    w.show()
    QTest.mouseClick(b, Qt.LeftButton)
    assert fx.historial[-1] == "clic"
    for icono, esperado in ((QMessageBox.Warning, "error"), (QMessageBox.Critical, "error"),
                            (QMessageBox.Information, "exito"), (QMessageBox.Question, "aviso")):
        fx._ultimo = 0
        m = QMessageBox(icono, "Oceánica", "texto")
        m.show()
        QApplication.processEvents()
        assert fx.historial[-1] == esperado
        m.close()
    # diálogos con su propio sonido (el ticket al terminar un cobro)
    from oceanica.app.dialogos import TicketDialog
    assert TicketDialog.sonido_al_abrir == "exito"
    w.close()


def test_brillo_al_escribir_se_enciende_y_se_quita(fx):
    for v in QApplication.topLevelWidgets():           # ventanas que dejaron otras pruebas no deben robar el foco
        v.hide()
    w = QWidget()
    lay = QVBoxLayout(w)
    campo, siguiente = QLineEdit(), QLineEdit()
    lay.addWidget(campo)
    lay.addWidget(siguiente)
    w.show()
    w.activateWindow()
    QTest.qWaitForWindowActive(w)
    campo.setFocus()
    QTest.qWait(220)
    assert campo.graphicsEffect() is not None and campo.graphicsEffect().blurRadius() > 10
    QTest.keyClick(campo, Qt.Key_A)                     # pulso al teclear, sin errores
    assert campo.text() == "a" and campo.graphicsEffect() is not None
    siguiente.setFocus()                                # pasa al siguiente campo: el primero se apaga
    QTest.qWait(300)
    assert campo.graphicsEffect() is None and id(campo) not in fx._brillos
    assert siguiente.graphicsEffect() is not None

    # un campo que ya tiene otro efecto no se toca; con animaciones apagadas, nada
    from PySide6.QtWidgets import QGraphicsBlurEffect
    otro = QLineEdit(w)
    propio = QGraphicsBlurEffect(otro)
    otro.setGraphicsEffect(propio)
    QApplication.sendEvent(otro, QFocusEvent(QEvent.FocusIn, Qt.TabFocusReason))
    assert otro.graphicsEffect() is propio
    fx.configurar(sonidos=True, animaciones=False)
    tercero = QLineEdit(w)
    QApplication.sendEvent(tercero, QFocusEvent(QEvent.FocusIn, Qt.TabFocusReason))
    assert tercero.graphicsEffect() is None
    w.close()


def test_sacudir_y_aparecer_regresan_a_su_lugar(fx):
    w = QWidget()
    w.resize(400, 200)
    lay = QVBoxLayout(w)
    hijo = QPushButton("x")
    lay.addWidget(hijo)
    w.show()
    QApplication.processEvents()
    base = hijo.pos()
    fx.sacudir(hijo)
    QTest.qWait(320)
    assert hijo.pos() == base                  # termina donde empezó: no deja la pantalla movida
    fx.aparecer(hijo)
    assert hijo.pos().x() > base.x()           # arranca corrido a la derecha
    QTest.qWait(320)
    assert hijo.pos() == base
    w.close()


def test_interruptores_en_configuracion(conn, admin):
    from oceanica.servicios import configuracion
    from oceanica.servicios.comunes import ErrorNegocio
    e = Efectos()
    e.configurar_desde(conn)
    assert e.sonidos and e.animaciones                    # encendidos por omisión (migración 015)
    configuracion.establecer(conn, admin, "interfaz_sonidos", "no")
    configuracion.establecer(conn, admin, "interfaz_animaciones", "no")
    e.configurar_desde(conn)
    assert not e.sonidos and not e.animaciones
    with pytest.raises(ErrorNegocio):
        configuracion.establecer(conn, admin, "interfaz_sonidos", "tal vez")


def test_pantalla_de_carga_espera_en_hilo_y_devuelve_errores(monkeypatch):
    preparar_aplicacion()
    from oceanica.app import carga
    from oceanica.app.carga import PantallaCarga, iniciar_pantalla_carga
    monkeypatch.setattr(carga, "MINIMO_VISIBLE", 0.0)
    assert iniciar_pantalla_carga() is None                # sin pantalla (pruebas) no se muestra
    p = PantallaCarga()
    assert p.esperar("Conectando…", lambda a, b: a + b, 2, 3) == 5 and p.texto == "Conectando…"

    def falla():
        raise ValueError("sin base")
    with pytest.raises(ValueError, match="sin base"):
        p.esperar("Revisando…", falla)
    # el llenado del logo sigue el avance real, nunca retrocede, y al cerrar llega al 100 %
    p.avance(0.6)
    p.avance(0.3)
    assert p.objetivo == 0.6
    QTest.qWait(400)
    assert 0 < p.progreso <= 0.6
    p.show()
    p.cerrar()
    assert p.progreso == 1.0
    QTest.qWait(500)
    assert not p.isVisible()
    img = p.grab()                                         # se dibuja sin errores (burbuja, logo, burbujas)
    assert not img.isNull()


def test_entrada_admin_avisa_y_sacude_en_error(conn, admin, monkeypatch):
    preparar_aplicacion()
    from oceanica.app import login as m_login
    from oceanica.app.contexto import Contexto
    sacudidas = []
    monkeypatch.setattr(m_login.efectos, "sacudir", lambda w: sacudidas.append(w))
    monkeypatch.setattr(m_login.efectos, "sonidos", True)
    v = m_login.LoginView(Contexto(conn))
    v.b_admin.click()                                      # vacío: pide los datos sin ir a la base
    assert "usuario y su contraseña" in v.msg.text() and sacudidas == [v.card]
    v.usuario.setText(admin["usuario"])
    v.password.setText("incorrecta")
    v.b_admin.click()
    assert "incorrectos" in v.msg.text() and len(sacudidas) == 2 and v.password.text() == ""
    assert m_login.bloq_mayus_activado() is False          # fuera de Windows no se puede saber: apagado
    entradas = []
    v.entrar_admin.connect(entradas.append)
    from oceanica.seguridad import hashear
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET password_hash = %s WHERE id = %s", (hashear("Correcta#2026"), admin["id"]))
    conn.commit()
    v.password.setText("Correcta#2026")
    v.b_admin.click()
    assert entradas and entradas[0]["rol"] == "administrador"


def test_login_tiene_boton_olvido_y_abre_dialogo(conn, admin, monkeypatch):
    preparar_aplicacion()
    from oceanica.app import login as m_login
    from oceanica.app.contexto import Contexto
    v = m_login.LoginView(Contexto(conn))
    assert v.b_olvido.text() == "¿Olvidó su contraseña?"
    abiertos = []
    monkeypatch.setattr(m_login.RestablecerAdminDialog, "exec", lambda self: (abiertos.append(self.usuario.text()), 0)[1])
    v.usuario.setText(admin["usuario"])
    v.b_olvido.click()
    assert abiertos == [admin["usuario"]]        # abre el diálogo con el usuario ya puesto


def test_probar_sonido_no_truena(conn, admin, monkeypatch):
    preparar_aplicacion()
    from PySide6.QtWidgets import QMessageBox
    from oceanica.app.v_config import ConfigView
    from oceanica.app.contexto import Contexto
    avisos = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: avisos.append(a[2]))
    ctx = Contexto(conn); ctx.admin = admin
    v = ConfigView(ctx)
    v.probar_sonido()                            # fuera de Windows no suena, pero no debe fallar ni colgarse
    from oceanica.app.efectos import efectos as fx
    assert fx.historial[-1] == "exito"
