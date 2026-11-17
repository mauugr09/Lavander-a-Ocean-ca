"""Funciones de operación diaria: corte a ciegas, aviso de respaldo, aviso por WhatsApp, ropa olvidada,
ruta de domicilio y etiquetas de bolsa. Servicios contra la base real y pantallas con Qt sin pantalla."""
import os
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox  # noqa: E402

from oceanica import respaldos  # noqa: E402
from oceanica.app.contexto import Contexto  # noqa: E402
from oceanica.servicios import avisos, caja, clientes, configuracion, ordenes, reportes, tickets  # noqa: E402
from oceanica.servicios.comunes import ErrorNegocio  # noqa: E402

from .test_app import _sin_dialogos, _vista_ordenes, mundo, qapp  # noqa: E402,F401  (fixtures compartidas)

D = Decimal


def _sql(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    filas = cur.fetchall() if cur.description else None
    conn.commit()
    cur.close()
    return filas


def _orden(conn, admin, empleado, mundo, telefono="55 1234 5678", entrega=None, pagar=False, lista=True):
    """Orden de 2 edredones ($240) de una clienta con teléfono."""
    if not caja.corte_abierto(conn):
        caja.abrir_corte(conn, admin, 100)
    cid = clientes.crear_cliente(conn, admin, "María", "Ñúñez", telefono)
    oid = ordenes.crear_orden(conn, empleado, [{"servicio_id": mundo["pieza"], "cantidad": 2}], cliente_id=cid,
                              entrega=entrega)
    if pagar:
        efectivo = [m for m in caja.listar_metodos(conn) if m["es_efectivo"]][0]["id"]
        caja.registrar_pago(conn, empleado, oid, efectivo, ordenes.obtener_orden(conn, oid)["saldo"])
    if lista:
        ordenes.cambiar_estado(conn, empleado, oid, "en_proceso")
        ordenes.cambiar_estado(conn, empleado, oid, "lista")
    return oid


# ---------- corte a ciegas ------------------------------------------------------

def test_corte_a_ciegas_no_le_dice_al_empleado_cuanto_falta(conn, admin, empleado):
    caja.abrir_corte(conn, admin, 500)
    caja.registrar_movimiento(conn, empleado, "gasto", "Jabón", D("120"))       # esperado: 380
    with pytest.raises(ErrorNegocio) as e:
        caja.cerrar_corte(conn, empleado, 300)
    mensaje = str(e.value)
    assert mensaje.startswith("Hay una diferencia")
    assert "380" not in mensaje and "80" not in mensaje and "$" not in mensaje  # ni lo esperado ni la diferencia
    with pytest.raises(ErrorNegocio):
        caja.cerrar_corte(conn, empleado, 350)                                   # prueba otro monto: sigue sin saber
    with pytest.raises(ErrorNegocio, match=r"\$-30\.00.*\$380\.00"):
        caja.cerrar_corte(conn, admin, 350)                                      # la encargada sí ve las cifras
    assert caja.corte_abierto(conn) is not None                                  # nada se cerró

    corte_id = caja.corte_abierto(conn)["id"]
    intentos = caja.conteos_rechazados(conn, admin, corte_id)
    assert [(i["usuario"], i["detalle"].split(",")[0]) for i in intentos] == [
        ("cajero", "contó $300.00"), ("cajero", "contó $350.00"), ("admin", "contó $350.00")]
    with pytest.raises(Exception):
        caja.conteos_rechazados(conn, empleado, corte_id)                        # el empleado no ve la bitácora

    r = caja.cerrar_corte(conn, empleado, 350, "Faltaron 30, se revisa mañana")  # con explicación sí cierra
    assert r["diferencia"] == D("-30.00") and caja.corte_abierto(conn) is None


def test_corte_que_cuadra_cierra_sin_explicacion_y_sin_rechazos(conn, admin, empleado):
    caja.abrir_corte(conn, admin, 200)
    corte_id = caja.corte_abierto(conn)["id"]
    assert caja.cerrar_corte(conn, empleado, 200)["diferencia"] == 0
    assert caja.conteos_rechazados(conn, admin, corte_id) == []


def test_pantalla_de_caja_oculta_el_dinero_al_empleado(qapp, conn, admin, empleado, mundo, monkeypatch):
    from oceanica.app.v_caja import CajaView
    _sin_dialogos(monkeypatch)
    caja.abrir_corte(conn, admin, 500)
    caja.registrar_movimiento(conn, empleado, "gasto", "Jabón", D("120"))
    ctx = Contexto(conn)
    vista = CajaView(ctx)                                 # modo mostrador
    vista.al_mostrar()
    assert vista.tabla_res.isHidden() and not vista.lb_ciego.isHidden()
    assert vista.tabla_mov.rowCount() == 1                # los movimientos sí se ven
    ctx.admin = admin
    vista.al_mostrar()
    assert not vista.tabla_res.isHidden() and vista.lb_ciego.isHidden()
    textos = [vista.tabla_res.item(r, 0).text() + " " + vista.tabla_res.item(r, 1).text()
              for r in range(vista.tabla_res.rowCount())]
    assert "Efectivo esperado en caja $380.00" in textos
    vista.close()


# ---------- aviso de respaldo ---------------------------------------------------

def _respaldo(conn, hace: timedelta, externo: int, nombre="oceanica_x.sql.gz"):
    _sql(conn, "INSERT INTO respaldos (archivo, tamano_bytes, tipo, copiado_a_externo, creado_en) VALUES (%s, 10, 'automatico', %s, %s)",
         (nombre, externo, datetime(2026, 11, 17, 21, 0) - hace))


def test_estado_del_respaldo(conn, tmp_path):
    ahora = datetime(2026, 11, 17, 21, 0)
    e = respaldos.estado(conn, ahora, tmp_path)
    assert (e["nivel"], e["mensaje"], e["ultimo"]) == ("alerta", "Nunca se ha hecho un respaldo", None)

    (tmp_path / "oceanica_x.sql.gz").write_bytes(b"x")
    _respaldo(conn, timedelta(days=6), 1)
    e = respaldos.estado(conn, ahora, tmp_path)
    assert (e["nivel"], e["mensaje"], e["dias"]) == ("alerta", "Último respaldo: hace 6 días", 6)

    _respaldo(conn, timedelta(hours=22), 0)               # el de anoche, sin USB conectada
    e = respaldos.estado(conn, ahora, tmp_path)
    assert (e["nivel"], e["mensaje"]) == ("aviso", "Respaldo de ayer, sin copia en disco externo")

    _respaldo(conn, timedelta(hours=1), 1)
    assert respaldos.estado(conn, ahora, tmp_path) == {
        "nivel": "ok", "mensaje": "Respaldo de hoy, con copia externa", "ultimo": datetime(2026, 11, 17, 20, 0), "dias": 0}

    _respaldo(conn, timedelta(minutes=5), 1, "oceanica_borrado.sql.gz")   # está en la bitácora pero no en el disco
    e = respaldos.estado(conn, ahora, tmp_path)
    assert (e["nivel"], e["mensaje"]) == ("alerta", "El respaldo de hoy ya no está en la carpeta")


def test_la_ventana_avisa_del_respaldo_solo_a_la_encargada(qapp, conn, admin, mundo):
    from oceanica.app.ventana import Ventana
    v = Ventana(Contexto(conn))
    v.abrir_shell(None)                                   # mostrador: sin aviso
    assert v.chip_respaldo.isHidden()
    v.mostrar_login()
    v.abrir_shell(admin)
    assert not v.chip_respaldo.isHidden() and v.chip_respaldo.text() == "Nunca se ha hecho un respaldo"
    assert v.chip_respaldo.property("rol") == "chip_alerta"
    v.mostrar_login()
    v.close()


# ---------- aviso por WhatsApp --------------------------------------------------

@pytest.mark.parametrize("escrito", ["5512345678", "55 1234 5678", "(55) 1234-5678", "+52 55 1234 5678",
                                     "+52 1 55 1234 5678", "525512345678"])
def test_telefono_para_whatsapp(escrito):
    assert avisos.telefono_whatsapp(escrito) == "525512345678"


@pytest.mark.parametrize("malo", ["", None, "1234567", "55123456789", "+1 415 555 2671"])
def test_telefono_invalido_no_arma_enlace(malo):
    with pytest.raises(ErrorNegocio):
        avisos.telefono_whatsapp(malo)


def test_aviso_de_orden_lista(conn, admin, empleado, mundo):
    oid = _orden(conn, admin, empleado, mundo, lista=False)
    with pytest.raises(ErrorNegocio, match="está lista"):
        avisos.aviso_orden_lista(conn, oid)               # todavía no está lista
    with pytest.raises(ErrorNegocio):
        avisos.registrar_aviso(conn, empleado, oid)
    ordenes.cambiar_estado(conn, empleado, oid, "en_proceso")
    ordenes.cambiar_estado(conn, empleado, oid, "lista")

    a = avisos.aviso_orden_lista(conn, oid)
    folio = ordenes.obtener_orden(conn, oid)["folio"]
    assert a["telefono"] == "525512345678" and a["avisado_en"] is None
    assert a["mensaje"].startswith("Hola María, le saluda ")
    assert f"orden {folio} ya está lista" in a["mensaje"] and "Saldo por pagar: $240.00." in a["mensaje"]
    assert "recogerla con su ticket" in a["mensaje"]
    url = urlparse(a["enlace"])
    assert (url.scheme, url.netloc, url.path) == ("https", "wa.me", "/525512345678")
    assert parse_qs(url.query)["text"] == [a["mensaje"]]  # acentos y signos bien codificados

    assert ordenes.obtener_orden(conn, oid)["avisado_en"] is None     # armar el mensaje no anota nada
    avisos.registrar_aviso(conn, empleado, oid)
    o = ordenes.obtener_orden(conn, oid)
    assert o["avisado_en"] is not None and o["avisado_por"] == empleado["id"]
    assert avisos.aviso_orden_lista(conn, oid)["avisado_en"] == o["avisado_en"]


def test_aviso_pagado_a_domicilio_y_sin_telefono(conn, admin, empleado, mundo):
    oid = _orden(conn, admin, empleado, mundo, entrega={"tipo": "domicilio", "direccion": "Av. Hidalgo 12"}, pagar=True)
    m = avisos.aviso_orden_lista(conn, oid)["mensaje"]
    assert "Ya está pagada." in m and "La llevaremos a su domicilio." in m and "Saldo" not in m

    sin_cliente = ordenes.crear_orden(conn, empleado, [{"servicio_id": mundo["pieza"], "cantidad": 1}])
    ordenes.cambiar_estado(conn, empleado, sin_cliente, "en_proceso")
    ordenes.cambiar_estado(conn, empleado, sin_cliente, "lista")
    with pytest.raises(ErrorNegocio, match="no hay a quién avisar"):
        avisos.aviso_orden_lista(conn, sin_cliente)


def test_avisar_desde_la_pantalla_de_ordenes(qapp, conn, admin, empleado, mundo, monkeypatch):
    from oceanica.app import v_ordenes
    oid = _orden(conn, admin, empleado, mundo)
    ctx, ov = _vista_ordenes(conn, empleado, monkeypatch)
    abiertos = []
    monkeypatch.setattr(v_ordenes.QDesktopServices, "openUrl", lambda url: abiertos.append(url.toString()) or True)
    assert ov.b_avisar.isEnabled() and "Todavía no se le avisa" in ov.detalle.toPlainText()

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)   # abrió WhatsApp pero no lo envió
    ov.avisar()
    assert len(abiertos) == 1 and abiertos[0].startswith("https://wa.me/525512345678?text=Hola")
    assert ordenes.obtener_orden(conn, oid)["avisado_en"] is None

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    ov.avisar()
    assert ordenes.obtener_orden(conn, oid)["avisado_en"] is not None
    assert "Se le avisó por WhatsApp" in ov.detalle.toPlainText()

    ordenes.cambiar_estado(conn, admin, oid, "entregada", "prueba", True)
    ov.recargar()
    assert not ov.b_avisar.isEnabled()
    ov.close()


# ---------- ropa olvidada y ruta de domicilio -----------------------------------

def test_reporte_de_ropa_olvidada(conn, admin, empleado, mundo):
    vieja = _orden(conn, admin, empleado, mundo)                       # lista hace 45 días
    reciente = _orden(conn, admin, empleado, mundo, telefono="5599998888")   # lista hoy
    en_proceso = _orden(conn, admin, empleado, mundo, telefono="5577776666", lista=False)   # vieja pero no lista
    _sql(conn, "UPDATE orden_historial_estado SET cambiado_en = NOW() - INTERVAL 45 DAY WHERE orden_id = %s", (vieja,))
    _sql(conn, "UPDATE ordenes SET fecha_recepcion = NOW() - INTERVAL 90 DAY WHERE id = %s", (en_proceso,))
    r = reportes.ropa_olvidada(conn)
    assert [f["folio"] for f in r["filas"]] == [ordenes.obtener_orden(conn, vieja)["folio"]]
    f = r["filas"][0]
    assert (f["dias"], f["saldo"], f["telefono"], f["avisado_en"]) == (45, D("240.00"), "55 1234 5678", None)
    assert r["totales"]["saldo"] == D("240.00") and "30 días" in r["subtitulo"]

    configuracion.establecer(conn, admin, "almacenaje_dias", "0")      # con 0 días entran todas las listas
    try:
        assert len(reportes.ropa_olvidada(conn)["filas"]) == 2
    finally:
        configuracion.establecer(conn, admin, "almacenaje_dias", "30")
    ordenes.cambiar_estado(conn, admin, vieja, "entregada", "prueba", True)
    assert reportes.ropa_olvidada(conn)["filas"] == []                 # entregada: ya no está olvidada
    assert reciente


def test_reporte_de_entregas_a_domicilio(conn, admin, empleado, mundo):
    dom = {"tipo": "domicilio", "direccion": "Calle Morelos 5, Centro"}
    en_proceso = _orden(conn, admin, empleado, mundo, entrega=dom, lista=False)
    lista = _orden(conn, admin, empleado, mundo, telefono="5599998888", entrega=dom, pagar=True)
    _orden(conn, admin, empleado, mundo, telefono="5577776666")        # recoge en mostrador: no va en la ruta
    entregada = _orden(conn, admin, empleado, mundo, telefono="5566665555", entrega=dom, pagar=True)
    ordenes.cambiar_estado(conn, empleado, entregada, "entregada")
    r = reportes.entregas_domicilio(conn)
    folios = [ordenes.obtener_orden(conn, i)["folio"] for i in (lista, en_proceso)]
    assert [f["folio"] for f in r["filas"]] == folios                 # primero la que ya está lista
    assert [(f["estado"], f["saldo"]) for f in r["filas"]] == [("Lista", D("0.00")), ("Recibida", D("240.00"))]
    assert r["filas"][0]["direccion_entrega"] == "Calle Morelos 5, Centro"
    assert r["totales"]["saldo"] == D("240.00")


def test_los_reportes_nuevos_estan_en_la_pantalla(qapp, conn, admin, empleado, mundo, monkeypatch):
    from oceanica.app import v_reportes
    _sin_dialogos(monkeypatch)
    _orden(conn, admin, empleado, mundo, entrega={"tipo": "domicilio", "direccion": "Calle Morelos 5"})
    ctx = Contexto(conn)
    ctx.admin = admin
    vista = v_reportes.ReportesView(ctx)
    vista.al_mostrar()
    for titulo, filas in (("Entregas a domicilio", 1), ("Ropa olvidada", 0)):
        vista.selector.setCurrentIndex(vista.selector.findText(titulo))
        assert vista.reporte["titulo"] == titulo and len(vista.reporte["filas"]) == filas
    vista.close()


# ---------- etiquetas de bolsa --------------------------------------------------

def test_etiquetas_de_bolsa(conn, admin, empleado, mundo):
    oid = _orden(conn, admin, empleado, mundo, entrega={"tipo": "domicilio", "direccion": "Calle Morelos 5"})
    o = ordenes.obtener_orden(conn, oid)
    t = tickets.etiquetas_bolsa_texto(conn, oid, 3)
    ancho = int(configuracion.obtener(conn, "ticket_ancho", "42"))
    assert all(len(linea) <= ancho for linea in t.splitlines())
    assert t.count(o["folio"]) == 3 and t.count("MARÍA ÑÚÑEZ") == 3
    assert all(f"BOLSA {n} DE 3" in t for n in (1, 2, 3)) and "BOLSA 4" not in t
    assert t.count("A DOMICILIO") == 3 and "POR COBRAR $" in t
    for malo in (0, 31, "muchas", None):
        with pytest.raises(ErrorNegocio):
            tickets.etiquetas_bolsa_texto(conn, oid, malo)


def test_etiquetas_desde_la_pantalla_de_ordenes(qapp, conn, admin, empleado, mundo, monkeypatch):
    from oceanica.app import dialogos, v_ordenes
    _orden(conn, admin, empleado, mundo)
    ctx, ov = _vista_ordenes(conn, empleado, monkeypatch)
    vistos = []
    monkeypatch.setattr(v_ordenes.QInputDialog, "getInt", lambda *a, **k: (2, True))
    monkeypatch.setattr(dialogos.TicketDialog, "exec", lambda self: vistos.append(self.texto) or 1)
    assert ov.b_etiquetas.isEnabled()
    ov.etiquetas()
    assert len(vistos) == 1 and "BOLSA 2 DE 2" in vistos[0]
    ov.close()
