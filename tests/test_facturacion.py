"""Factura (alcance mínimo, sin CFDI): datos fiscales del cliente, banderas de la orden y reporte mensual."""
import shutil
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from oceanica.config import CARPETA_MIGRACIONES
from oceanica.db import aplicar_migraciones, listar_migraciones
from oceanica.seguridad import ErrorAcceso
from oceanica.servicios import caja, catalogo, clientes, exportacion, facturacion, ordenes, reportes
from oceanica.servicios.comunes import ErrorNegocio

D = Decimal
FISCALES = {"rfc": "ABC010203XY1", "razon_social": "Hotel del Lago", "regimen_fiscal": "601", "uso_cfdi": "G03",
            "codigo_postal_fiscal": "54960"}


@pytest.fixture()
def servicio(conn, admin):
    cat = catalogo.listar_categorias(conn)[0]["id"]
    return catalogo.crear_servicio(conn, admin, cat, "Lavado y secado", "kilo", "30")


def _orden(conn, sesion, servicio, cliente_id, requiere=True):
    return ordenes.crear_orden(conn, sesion, [{"servicio_id": servicio, "cantidad": 2}], cliente_id,
                               requiere_factura=requiere)


# ---------- RFC y catálogos (sin base de datos) -------------------------------------------

@pytest.mark.parametrize("entrada,esperado", [
    ("ABC010203XY1", "ABC010203XY1"),           # persona moral, 12
    ("abcd-010203 xy1", "ABCD010203XY1"),       # persona física, 13; se normaliza
    ("ÑA&0002297A0", "ÑA&0002297A0"),           # Ñ y & son válidas; 29/feb/2000 existe
    ("GODE561231GR8", "GODE561231GR8"),
    ("", None), (None, None),
])
def test_rfc_valido_se_normaliza(entrada, esperado):
    assert facturacion.normalizar_rfc(entrada) == esperado


@pytest.mark.parametrize("malo", ["ABC", "AB010203XY1", "ABCDE010203XY1", "ABC011303XY1",   # mes 13
                                  "ABC010230XY1", "ABC010203XY", "ABC010203XYB", "ABC0102O3XY1", "123010203XY1"])
def test_rfc_con_formato_invalido_se_rechaza(malo):
    with pytest.raises(ErrorNegocio, match="RFC"):
        facturacion.normalizar_rfc(malo)


def test_regimen_uso_y_codigo_postal():
    v = facturacion.validar_datos_fiscales({"regimen_fiscal": "626", "uso_cfdi": "s01", "codigo_postal_fiscal": " 54960 "})
    assert v == {"regimen_fiscal": "626", "uso_cfdi": "S01", "codigo_postal_fiscal": "54960"}
    for campo, malo in (("regimen_fiscal", "999"), ("uso_cfdi", "CN01"), ("uso_cfdi", "CP01"),
                        ("codigo_postal_fiscal", "5496"), ("codigo_postal_fiscal", "5496A")):
        with pytest.raises(ErrorNegocio):
            facturacion.validar_datos_fiscales({campo: malo})
    assert facturacion.faltantes(FISCALES) == []
    assert facturacion.faltantes({"rfc": "ABC010203XY1"}) == ["razón social", "régimen fiscal", "uso del CFDI",
                                                              "código postal"]


# ---------- Migraciones -----------------------------------------------------------------

def test_actualizar_base_con_datos_desde_la_009(_base, tmp_path):
    """La base del cliente ya tiene datos: 010 y 011 se aplican sobre ella sin perder nada."""
    from tests.conftest import _vaciar_todo
    conn = _base
    _vaciar_todo(conn)
    for version, _, ruta in listar_migraciones():
        if version <= 9:
            shutil.copy(ruta, tmp_path / ruta.name)
    try:
        assert aplicar_migraciones(conn, tmp_path) == [1, 2, 3, 4, 5, 6, 7, 8, 9]
        cur = conn.cursor()
        cur.execute("INSERT INTO usuarios (rol_id, usuario, password_hash) VALUES (1, 'viejo', 'x')")
        uid = cur.lastrowid
        cur.execute("INSERT INTO clientes (nombre, telefono) VALUES ('Cliente previo', '5550001111')")
        cid = cur.lastrowid
        cur.execute("INSERT INTO ordenes (folio, cliente_id, usuario_id, total, tipo_entrega, cargo_domicilio, "
                    "direccion_entrega) VALUES ('OC-000001', %s, %s, 90, 'domicilio', 20, 'Calle 1')", (cid, uid))
        conn.commit()
    finally:
        assert aplicar_migraciones(conn, CARPETA_MIGRACIONES)[:2] == [10, 11]  # deja la base completa pase lo que pase
    cur.execute("SELECT nombre, rfc, razon_social FROM clientes")
    assert cur.fetchall() == [("Cliente previo", None, None)]
    cur.execute("SELECT folio, total, tipo_entrega, cargo_domicilio, requiere_factura, facturada, factura_folio FROM ordenes")
    assert cur.fetchall() == [("OC-000001", D("90.00"), "domicilio", D("20.00"), 0, 0, None)]
    assert aplicar_migraciones(conn) == []  # volver a migrar no hace nada
    cur.close()


# ---------- Datos fiscales del cliente ---------------------------------------------------

def test_cliente_con_datos_fiscales(conn, empleado):
    cid = clientes.crear_cliente(conn, empleado, "Hotel", None, "5512345678", "facturas@hotel.mx",
                                 **{**FISCALES, "rfc": "abc-010203-xy1"})
    c = clientes.obtener_cliente(conn, cid)
    assert {k: c[k] for k in FISCALES} == FISCALES          # RFC normalizado a mayúsculas sin guiones
    assert clientes.buscar_clientes(conn, "ABC0102")[0]["id"] == cid  # se encuentra por RFC
    clientes.actualizar_cliente(conn, empleado, cid, uso_cfdi="S01", codigo_postal_fiscal="")
    c = clientes.obtener_cliente(conn, cid)
    assert c["uso_cfdi"] == "S01" and c["codigo_postal_fiscal"] is None and c["rfc"] == "ABC010203XY1"
    with pytest.raises(ErrorNegocio, match="RFC"):
        clientes.actualizar_cliente(conn, empleado, cid, rfc="NOESRFC")
    with pytest.raises(ErrorNegocio, match="RFC"):
        clientes.crear_cliente(conn, empleado, "Otro", rfc="XX")
    with pytest.raises(ErrorNegocio, match="no editables"):
        clientes.crear_cliente(conn, empleado, "Otro", regimen="601")
    assert clientes.obtener_cliente(conn, cid)["rfc"] == "ABC010203XY1"  # el error no cambió nada


# ---------- Banderas de la orden ---------------------------------------------------------

def test_orden_que_requiere_factura_necesita_cliente(conn, empleado, servicio):
    with pytest.raises(ErrorNegocio, match="mostrador"):
        _orden(conn, empleado, servicio, None)
    assert ordenes.listar_ordenes(conn) == []
    oid = _orden(conn, empleado, servicio, None, requiere=False)
    with pytest.raises(ErrorNegocio, match="mostrador"):
        facturacion.marcar_requiere_factura(conn, empleado, oid)


def test_flujo_de_factura(conn, admin, empleado, servicio):
    cid = clientes.crear_cliente(conn, empleado, "Hotel", **FISCALES)
    oid = _orden(conn, empleado, servicio, cid, requiere=False)
    facturacion.marcar_requiere_factura(conn, empleado, oid)          # el empleado lo olvidó al capturar
    assert [o["id"] for o in ordenes.listar_ordenes(conn, por_facturar=True)] == [oid]

    with pytest.raises(ErrorAcceso):
        facturacion.marcar_facturada(conn, empleado, oid, "A-15")      # solo la encargada
    facturacion.marcar_facturada(conn, admin, oid, " A-15 ")
    o = ordenes.obtener_orden(conn, oid)
    assert o["facturada"] == 1 and o["factura_folio"] == "A-15" and o["facturo"] == "admin" and o["facturada_en"]
    assert ordenes.listar_ordenes(conn, por_facturar=True) == []
    with pytest.raises(ErrorNegocio, match="ya está marcada"):
        facturacion.marcar_facturada(conn, admin, oid)
    with pytest.raises(ErrorNegocio, match="quitar primero"):
        facturacion.marcar_requiere_factura(conn, empleado, oid, False)
    with pytest.raises(ErrorNegocio, match="facturada"):
        ordenes.cancelar_orden(conn, admin, oid, "Se equivocó")       # no se cancela con un CFDI vigente

    with pytest.raises(ErrorAcceso):
        facturacion.desmarcar_facturada(conn, empleado, oid, "x")
    with pytest.raises(ErrorNegocio, match="motivo"):
        facturacion.desmarcar_facturada(conn, admin, oid, " ")
    facturacion.desmarcar_facturada(conn, admin, oid, "Factura cancelada en el SAT")
    o = ordenes.obtener_orden(conn, oid)
    assert o["facturada"] == 0 and o["factura_folio"] is None and o["requiere_factura"] == 1
    ordenes.cancelar_orden(conn, admin, oid, "El cliente ya no la quiso")
    with pytest.raises(ErrorNegocio, match="cancelada"):
        facturacion.marcar_facturada(conn, admin, oid)

    cur = conn.cursor()
    cur.execute("SELECT accion FROM auditoria WHERE tabla = 'ordenes' AND registro_id = %s ORDER BY id", (oid,))
    acciones = [a for (a,) in cur.fetchall()]
    cur.close()
    assert acciones == ["orden_creada", "factura_solicitada", "orden_facturada", "orden_factura_quitada", "orden_cancelada"]


def test_marcar_facturada_sin_haberla_pedido_la_pide(conn, admin, servicio):
    cid = clientes.crear_cliente(conn, admin, "Hotel")
    oid = _orden(conn, admin, servicio, cid, requiere=False)
    facturacion.marcar_facturada(conn, admin, oid)                     # el folio es opcional
    o = ordenes.obtener_orden(conn, oid)
    assert o["requiere_factura"] == 1 and o["facturada"] == 1 and o["factura_folio"] is None


# ---------- Reporte mensual --------------------------------------------------------------

def _fechar(conn, oid, cuando):
    cur = conn.cursor()
    cur.execute("UPDATE ordenes SET fecha_recepcion = %s WHERE id = %s", (cuando, oid))
    conn.commit()
    cur.close()


def test_reporte_por_facturar_y_excel(conn, admin, empleado, servicio, tmp_path):
    completo = clientes.crear_cliente(conn, empleado, "Hotel", email="f@hotel.mx", **FISCALES)
    incompleto = clientes.crear_cliente(conn, empleado, "Taller", rfc="TAL0102037A1")
    caja.abrir_corte(conn, admin, 0)
    efectivo = [m for m in caja.listar_metodos(conn) if m["es_efectivo"]][0]["id"]
    hoy = date.today()
    inicio = hoy.replace(day=1)

    del_mes = _orden(conn, empleado, servicio, completo)
    caja.registrar_pago(conn, empleado, del_mes, efectivo, 20)
    anterior = _orden(conn, empleado, servicio, incompleto)
    _fechar(conn, anterior, datetime.combine(inicio - timedelta(days=3), datetime.min.time()))
    ya_facturada = _orden(conn, empleado, servicio, completo)
    facturacion.marcar_facturada(conn, admin, ya_facturada, "B-1")
    cancelada = _orden(conn, empleado, servicio, completo)
    ordenes.cancelar_orden(conn, empleado, cancelada, "Error de captura")
    _orden(conn, empleado, servicio, completo, requiere=False)         # no pidió factura
    futura = _orden(conn, empleado, servicio, completo)
    _fechar(conn, futura, datetime.combine(hoy + timedelta(days=40), datetime.min.time()))

    with pytest.raises(ErrorAcceso):
        reportes.por_facturar(conn, empleado, inicio, hoy)              # el reporte lleva RFC: solo la encargada
    r = reportes.por_facturar(conn, admin, inicio, hoy)
    filas = {f["folio"]: f for f in r["filas"]}
    assert set(filas) == {ordenes.obtener_orden(conn, del_mes)["folio"], ordenes.obtener_orden(conn, anterior)["folio"]}
    f_mes = filas[ordenes.obtener_orden(conn, del_mes)["folio"]]
    f_ant = filas[ordenes.obtener_orden(conn, anterior)["folio"]]
    assert f_mes["periodo"] == "Del periodo" and f_mes["datos"] == "Completos"
    assert f_mes["rfc"] == "ABC010203XY1" and f_mes["saldo"] == D("40.00") and f_mes["pagado"] == D("20.00")
    assert f_ant["periodo"] == "Anterior" and f_ant["datos"].startswith("Falta: razón social")
    assert r["totales"]["total"] == D("120.00")

    destino = exportacion.exportar(r, tmp_path / "por_facturar.xlsx", "Lavandería Oceánica")
    from openpyxl import load_workbook
    ws = load_workbook(destino).active
    fila_enc = next(r for r in range(1, 40) if any(c.value == "RFC" for c in ws[r]))   # el diseño pone logo y resumen arriba
    encabezados = [c.value for c in ws[fila_enc]]
    assert "Razón social" in encabezados and "Datos fiscales" in encabezados
    col = encabezados.index("RFC") + 1
    valores = {ws.cell(row=i, column=col).value for i in (fila_enc + 1, fila_enc + 2)}
    assert valores == {"ABC010203XY1", "TAL0102037A1"}


def test_reporte_por_facturar_vacio(conn, admin):
    r = reportes.por_facturar(conn, admin, date.today(), date.today())
    assert r["filas"] == [] and r["totales"]["total"] == 0


def test_pdf_ancho_sin_encimar_y_con_ampersand(conn, admin, empleado, servicio, tmp_path):
    """El reporte de 14 columnas cabe en la hoja sin partir folios, RFC ni montos, y un «&» (válido en el RFC y en
    nombres como «Taller R&M») no rompe el PDF."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    cid = clientes.crear_cliente(conn, empleado, "Taller R&M", email="facturas@tallerryemecanica.com.mx",
                                 **{**FISCALES, "rfc": "R&M010203XY1", "razon_social": "TALLER R&M <NORTE>"})
    _orden(conn, empleado, servicio, cid)
    r = reportes.por_facturar(conn, admin, date.today().replace(day=1), date.today())
    destino = exportacion.exportar(r, tmp_path / "por_facturar.pdf", "Lavandería Oceánica")
    assert destino.stat().st_size > 1000
    tabla = exportacion._tabla_pdf(r, 700, exportacion._estilos())
    celdas = {c.getPlainText() if hasattr(c, "getPlainText") else str(c) for fila in tabla._cellvalues for c in fila}
    assert {"R&M010203XY1", "TALLER R&M <NORTE>", "Taller R&M"} <= celdas   # sin escapar salía «TALLER R&M;»

    cols = r["columnas"]
    textos = [[c[1] for c in cols]] + [[exportacion.formatear(f.get(c[0]), c[2]) for c in cols] for f in r["filas"]]
    anchos = exportacion._anchos_columnas(cols, textos, 700, [1.0] * len(cols))
    assert abs(sum(anchos) - 700) < 0.01
    for j, (clave, _, tipo) in enumerate(cols):
        if clave in ("folio", "rfc", "total", "fecha_recepcion"):
            assert anchos[j] >= stringWidth(textos[1][j], "Helvetica", 8.5), clave   # no se parte ni se encima
