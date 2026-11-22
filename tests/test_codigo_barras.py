"""Folio en código de barras (Code128) en el ticket y las etiquetas de bolsa, y lectura con escáner en Órdenes."""
from decimal import Decimal

import pytest

from oceanica.servicios import caja, catalogo, clientes, configuracion, ordenes, tickets

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from .test_app import _sin_dialogos, _vista_ordenes, mundo, qapp  # noqa: E402,F401  (fixtures compartidas)


@pytest.fixture()
def orden(conn, admin, empleado):
    cat = catalogo.listar_categorias(conn)[0]["id"]
    sid = catalogo.crear_servicio(conn, admin, cat, "Lavado y secado", "kilo", "30")
    cid = clientes.crear_cliente(conn, empleado, "Ana", "Núñez", "5511112222")
    return ordenes.crear_orden(conn, empleado, [{"servicio_id": sid, "cantidad": 3}], cid)


def _codigos(texto):
    return [c for c in (tickets.codigo_en_linea(l) for l in texto.split("\n")) if c]


def test_ticket_y_etiquetas_llevan_el_folio_en_barras(conn, admin, orden):
    folio = ordenes.obtener_orden(conn, orden)["folio"]
    assert configuracion.obtener(conn, "codigo_barras") == "si"           # migración 014: encendido
    assert _codigos(tickets.ticket_orden_texto(conn, orden)) == [folio]
    assert _codigos(tickets.etiquetas_bolsa_texto(conn, orden, 3)) == [folio] * 3   # uno por bolsa

    configuracion.establecer(conn, admin, "codigo_barras", "no")          # la encargada lo apaga
    try:
        assert _codigos(tickets.ticket_orden_texto(conn, orden)) == []
        assert _codigos(tickets.etiquetas_bolsa_texto(conn, orden, 2)) == []
    finally:  # la configuración no se vacía entre pruebas: se deja como estaba
        configuracion.establecer(conn, admin, "codigo_barras", "si")


def test_escpos_manda_code128_y_no_la_marca(conn, orden):
    folio = ordenes.obtener_orden(conn, orden)["folio"]
    datos = tickets._texto_escpos(tickets.ticket_orden_texto(conn, orden))
    contenido = b"{B" + folio.encode()
    assert b"\x1dk\x49" + bytes([len(contenido)]) + contenido in datos    # GS k 73 n {B folio
    assert b"[[CODIGO" not in datos
    assert "Núñez".encode("cp850") in datos                              # el resto sigue en cp850


def test_pdf_dibuja_las_barras(conn, orden, tmp_path, monkeypatch):
    folio = ordenes.obtener_orden(conn, orden)["folio"]
    dibujados = []
    original = tickets.code128.Code128.drawOn
    monkeypatch.setattr(tickets.code128.Code128, "drawOn",
                        lambda self, *a, **k: (dibujados.append(self.value), original(self, *a, **k))[1])
    ruta = tickets.texto_a_pdf_ticket(tickets.etiquetas_bolsa_texto(conn, orden, 2), tmp_path / "e.pdf")
    assert ruta.stat().st_size > 1000 and dibujados == [folio, folio]
    assert b"[[CODIGO" not in ruta.read_bytes()


def test_en_pantalla_se_ve_el_folio_no_la_marca():
    vista = tickets.para_pantalla("Hola\n[[CODIGO:OC-000123]]\nAdiós", 30)
    assert "[[" not in vista and "|||| OC-000123 ||||" in vista and vista.startswith("Hola\n")
    assert tickets.codigo_en_linea("[[CODIGO:OC]]X]]") is None              # «]» no cabe en la marca
    assert tickets.codigo_en_linea("  [[CODIGO:oc-7]]  ") == "oc-7"


def test_escanear_el_folio_en_ordenes_encuentra_la_orden_aunque_ya_se_entrego(qapp, conn, admin, empleado, mundo,
                                                                                 monkeypatch):
    caja.abrir_corte(conn, admin, 0)
    ef = [m["id"] for m in caja.listar_metodos(conn) if m["es_efectivo"]][0]
    ids = [ordenes.crear_orden(conn, empleado, [{"servicio_id": mundo["kilo"], "cantidad": 2}]) for _ in range(3)]
    entregada = ids[1]
    caja.registrar_pago(conn, empleado, entregada, ef, ordenes.obtener_orden(conn, entregada)["total"])
    ordenes.cambiar_estado(conn, empleado, entregada, "entregada")
    folio = ordenes.obtener_orden(conn, entregada)["folio"]

    ctx, ov = _vista_ordenes(conn, empleado, monkeypatch)
    assert ov.filtro.currentData() is None                                # «Pendientes de entregar»
    ov.buscar.setText(folio.lower())                                      # el lector escribe el folio…
    ov._enter_en_busqueda()                                               # …y Enter
    assert ov.filtro.currentData() == "todas" and ov.orden["id"] == entregada


def test_la_vista_previa_del_ticket_muestra_el_folio(qapp, conn, orden, monkeypatch):
    from oceanica.app.dialogos import TicketDialog
    from PySide6.QtWidgets import QPlainTextEdit
    _sin_dialogos(monkeypatch)
    dlg = TicketDialog(None, tickets.ticket_orden_texto(conn, orden), "x.pdf")
    texto = dlg.findChild(QPlainTextEdit).toPlainText()
    assert "[[CODIGO" not in texto and "||||" in texto
    assert QMessageBox  # (usado por _sin_dialogos)
