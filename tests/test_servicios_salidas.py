"""Integración: reportes, exportaciones, tickets y carga inicial contra una base real."""
import csv
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from openpyxl import Workbook, load_workbook

from oceanica.seguridad import ErrorAcceso
from oceanica.servicios import (caja, carga_inicial, catalogo, clientes, configuracion, empleados, exportacion,
                                inventario, nomina, ordenes, reportes, tickets)
from oceanica.servicios.comunes import ErrorNegocio

D = Decimal
HOY = date.today()


def _metodo(conn, nombre):
    cur = conn.cursor()
    cur.execute("SELECT id FROM metodos_pago WHERE nombre = %s", (nombre,))
    return cur.fetchone()[0]


@pytest.fixture()
def negocio(conn, admin, empleado):
    """Dos órdenes cobradas parcial o totalmente y una cancelada, con caja abierta."""
    cat = catalogo.listar_categorias(conn)[0]["id"]
    kilo = catalogo.crear_servicio(conn, admin, cat, "Lavado y secado", "kilo", "28.50")
    pieza = catalogo.crear_servicio(conn, admin, cat, "Edredón", "pieza", 120)
    cid = clientes.crear_cliente(conn, empleado, "Ana", "Torres", "5511112222")
    caja.abrir_corte(conn, empleado, 100)
    a = ordenes.crear_orden(conn, empleado, [{"servicio_id": kilo, "cantidad": 4}], cliente_id=cid)  # 114
    b = ordenes.crear_orden(conn, empleado, [{"servicio_id": pieza, "cantidad": 2}])  # 240
    c = ordenes.crear_orden(conn, empleado, [{"servicio_id": kilo, "cantidad": 1}])
    caja.registrar_pago(conn, empleado, a, _metodo(conn, "Efectivo"), 114)
    caja.registrar_pago(conn, empleado, b, _metodo(conn, "Tarjeta"), 100)
    ordenes.cancelar_orden(conn, empleado, c, "Se equivocó")
    cur = conn.cursor()
    cur.execute("UPDATE ordenes SET fecha_promesa = %s WHERE id = %s", (datetime.now() - timedelta(days=3), b))
    conn.commit()
    return {"a": a, "b": b, "c": c, "cliente": cid, "kilo": kilo, "pieza": pieza}


# ---------- reportes -------------------------------------------------------------

def test_resumen_general(conn, negocio):
    r = reportes.resumen_general(conn, HOY, HOY)
    assert r["ordenes"] == 2 and r["vendido"] == D("354.00") and r["cobrado"] == D("214.00")
    assert r["ticket_promedio"] == D("177.00") and r["kilos"] == D("4.00")
    assert r["ordenes_abiertas"] == 2 and r["ordenes_retrasadas"] == 1 and r["por_cobrar"] == D("140.00")
    assert r["clientes_nuevos"] == 1


def test_ventas_por_dia_y_metodo(conn, negocio):
    r = reportes.ventas_por_dia(conn, HOY - timedelta(days=2), HOY)
    assert len(r["filas"]) == 1 and r["filas"][0]["vendido"] == D("354.00")
    assert r["totales"]["cobrado"] == D("214.00")
    m = {f["metodo_pago"]: f["total"] for f in reportes.cobros_por_metodo(conn, HOY, HOY)["filas"]}
    assert m == {"Efectivo": D("114.00"), "Tarjeta": D("100.00")}


def test_ventas_por_servicio_excluye_canceladas(conn, negocio):
    r = {f["servicio"]: f for f in reportes.ventas_por_servicio(conn, HOY, HOY)["filas"]}
    assert r["Lavado y secado"]["importe"] == D("114.00") and r["Edredón"]["importe"] == D("240.00")


def test_ordenes_pendientes_con_retraso_y_saldo(conn, negocio):
    filas = reportes.ordenes_pendientes(conn)["filas"]
    assert [f["folio"] for f in filas] == ["OC-000002", "OC-000001"]  # la más atrasada primero
    assert filas[0]["dias_retraso"] == 3 and filas[0]["saldo"] == D("140.00")
    assert filas[1]["saldo"] == D("0.00")


def test_clientes_frecuentes(conn, negocio):
    f = reportes.clientes_frecuentes(conn)["filas"]
    assert len(f) == 1 and f[0]["cliente"] == "Ana Torres" and f[0]["num_ordenes"] == 1


def test_insumos_bajos_y_cortes_y_asistencia(conn, admin, empleado, negocio):
    cat = inventario.listar_categorias(conn)[0]["id"]
    inventario.crear_insumo(conn, admin, cat, "Suavizante", "litro", minimo=5, existencia_inicial=3)
    inventario.crear_insumo(conn, admin, cat, "Detergente", "litro", minimo=5, existencia_inicial=30)
    assert [f["nombre"] for f in reportes.insumos_bajos(conn)["filas"]] == ["Suavizante"]
    caja.cerrar_corte(conn, empleado, 214 + 100 - 100 + 0, "ajuste")  # esperado 100 + 114 = 214
    c = reportes.cortes_de_caja(conn, HOY, HOY)["filas"]
    assert len(c) == 1 and c[0]["estado"] == "cerrado" and c[0]["diferencia"] == D("0.00")
    eid = empleados.crear_empleado(conn, admin, "Eva", "Rey", "2026-01-01")
    empleados.corregir_asistencia(conn, admin, eid, HOY, datetime.combine(HOY, datetime.min.time()).replace(hour=9),
                                  datetime.combine(HOY, datetime.min.time()).replace(hour=17), "Captura")
    a = reportes.asistencia(conn, HOY, HOY)["filas"]
    assert a[0]["empleado"] == "Eva Rey" and a[0]["horas_trabajadas"] == D("8.00")


def test_costo_de_nomina_solo_admin(conn, admin, empleado, negocio):
    with pytest.raises(ErrorAcceso):
        reportes.costo_nomina_vs_ventas(conn, empleado, HOY, HOY)
    r = reportes.costo_nomina_vs_ventas(conn, admin, HOY, HOY)
    assert r["ventas"] == D("354.00") and r["nomina"] == D("0") and r["porcentaje"] == D("0.0")
    with pytest.raises(ErrorAcceso):
        reportes.nomina_periodo(conn, empleado, 1)


# ---------- exportaciones --------------------------------------------------------

def test_exportar_excel_con_totales(conn, negocio, tmp_path):
    rep = reportes.ventas_por_servicio(conn, HOY, HOY)
    ruta = exportacion.exportar(rep, tmp_path / "ventas.xlsx", "Lavandería Oceánica")
    hoja = load_workbook(ruta).active
    filas = list(hoja.iter_rows(values_only=True))
    assert filas[0][0] == "Lavandería Oceánica - Ventas por servicio"
    assert filas[3][0] == "Servicio" and filas[-1][0] == "TOTAL"
    assert filas[-1][4] == pytest.approx(354.0)


def test_exportar_pdf_y_formato_invalido(conn, negocio, tmp_path):
    ruta = exportacion.exportar(reportes.ordenes_pendientes(conn), tmp_path / "pend.pdf", "Oceánica")
    assert ruta.read_bytes().startswith(b"%PDF")
    with pytest.raises(ErrorNegocio):
        exportacion.exportar(reportes.ordenes_pendientes(conn), tmp_path / "x.doc")
    with pytest.raises(ErrorNegocio):  # reporte vacío
        exportacion.exportar(reportes.insumos_bajos(conn), tmp_path / "vacio.pdf")


# ---------- tickets --------------------------------------------------------------

def test_ticket_de_orden(conn, negocio, tmp_path):
    configuracion.establecer(conn, {"rol": "administrador", "id": 1}, "negocio_nombre", "Lavandería Oceánica")
    t = tickets.ticket_orden_texto(conn, negocio["b"])
    assert "OC-000002" in t and "TOTAL" in t and "240.00" in t
    assert "SALDO PENDIENTE" in t and "140.00" in t and "Tarjeta" in t
    assert all(len(l) <= 42 for l in t.splitlines())
    assert "Lavandería Oceánica" in t.splitlines()[0]
    pdf = tickets.ticket_orden_pdf(conn, negocio["a"], tmp_path / "ticket.pdf")
    assert pdf.read_bytes().startswith(b"%PDF")
    assert "CANCELADA" in tickets.ticket_orden_texto(conn, negocio["c"])


def test_ticket_se_adapta_al_ancho_configurado(conn, admin, negocio):
    configuracion.establecer(conn, admin, "ticket_ancho", "32")
    assert all(len(l) <= 32 for l in tickets.ticket_orden_texto(conn, negocio["b"]).splitlines())
    with pytest.raises(ErrorNegocio):
        configuracion.establecer(conn, admin, "ticket_ancho", "abc")


def test_ticket_de_corte(conn, empleado, negocio):
    t = tickets.ticket_corte_texto(conn, caja.corte_abierto(conn)["id"])
    assert "EFECTIVO ESPERADO" in t and "214.00" in t


def test_imprimir_sin_windows_da_error_claro():
    with pytest.raises(tickets.ErrorImpresion, match="pywin32"):
        tickets.imprimir_texto("hola")


def test_recibo_de_nomina(conn, admin, tmp_path):
    eid = empleados.crear_empleado(conn, admin, "Ana", "Torres", "2026-01-01")
    nomina.fijar_salario(conn, admin, eid, "quincena", 3000, "2026-01-01")
    pid = nomina.abrir_periodo(conn, admin, "quincenal", "2026-11-01", "2026-11-15")
    nomina.calcular_periodo(conn, admin, pid)
    nid = nomina.obtener_periodo(conn, admin, pid)["nominas"][0]["id"]
    ruta = tickets.recibo_nomina_pdf(conn, admin, nid, tmp_path / "recibo.pdf")
    assert ruta.read_bytes().startswith(b"%PDF")
    with pytest.raises(ErrorAcceso):
        tickets.recibo_nomina_pdf(conn, {"id": 9, "rol": "empleado"}, nid, tmp_path / "x.pdf")


# ---------- carga inicial --------------------------------------------------------

def _csv(ruta, filas, delim=","):
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f, delimiter=delim).writerows(filas)
    return ruta


def test_importar_servicios_csv_punto_y_coma_y_categorias_nuevas(conn, admin, tmp_path):
    ruta = _csv(tmp_path / "servicios.csv", [
        ["Categoría", "Nombre", "Unidad", "Precio"],
        ["Lavado por kilo", "Lavado y secado", "kilo", "$28.50"],
        ["Tintorería", "Traje 2 piezas", "pieza", "180,00"],
    ], delim=";")
    r = carga_inicial.importar(conn, admin, "servicios", ruta)
    assert r == {"insertados": 2, "omitidos": 0, "errores": []}
    s = {x["nombre"]: x for x in catalogo.listar_servicios(conn)}
    assert s["Lavado y secado"]["precio"] == D("28.50") and s["Traje 2 piezas"]["precio"] == D("180.00")
    assert s["Traje 2 piezas"]["categoria"] == "Tintorería"
    assert carga_inicial.importar(conn, admin, "servicios", ruta)["omitidos"] == 2  # reimportar no duplica


def test_importar_es_todo_o_nada(conn, admin, tmp_path):
    ruta = _csv(tmp_path / "s.csv", [["categoria", "nombre", "unidad", "precio"],
                                     ["Planchado", "Camisa", "pieza", "15"],
                                     ["Planchado", "Pantalón", "docena", "20"],
                                     ["Planchado", "Vestido", "pieza", "abc"]])
    r = carga_inicial.importar(conn, admin, "servicios", ruta)
    assert r["insertados"] == 0 and [e[0] for e in r["errores"]] == [3, 4]
    assert catalogo.listar_servicios(conn) == []


def test_importar_insumos_xlsx_con_existencia_inicial(conn, admin, tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Categoría", "Nombre", "Unidad", "Existencia", "Mínimo", "Costo", "Proveedor"])
    ws.append(["Detergentes", "Detergente líquido", "litro", 12, 5, 40, "Química del Centro"])
    ws.append(["Empaque", "Bolsas", "pieza", None, 100, 0.8, None])
    wb.save(tmp_path / "insumos.xlsx")
    r = carga_inicial.importar(conn, admin, "insumos", tmp_path / "insumos.xlsx")
    assert r["insertados"] == 2 and not r["errores"]
    det = [i for i in inventario.listar_insumos(conn) if i["nombre"] == "Detergente líquido"][0]
    assert det["existencia"] == D("12.00") and det["proveedor"] == "Química del Centro"
    assert len(inventario.movimientos_insumo(conn, det["id"])) == 1


def test_importar_empleados_y_clientes(conn, admin, tmp_path):
    r = carga_inicial.importar(conn, admin, "empleados", _csv(tmp_path / "e.csv", [
        ["Nombre", "Apellidos", "Teléfono", "Puesto", "Fecha de ingreso"],
        ["Luis", "Mora", "5500", "Planchador", "15/03/2025"]]))
    assert r["insertados"] == 1
    assert empleados.listar_empleados(conn)[0]["fecha_ingreso"] == date(2025, 3, 15)
    r = carga_inicial.importar(conn, admin, "clientes", _csv(tmp_path / "c.csv", [
        ["nombre", "apellidos", "telefono", "correo"], ["Rosa", "Díaz", "5511", "rosa@correo.mx"], ["Pablo", "", "", "malcorreo"]]))
    assert r["insertados"] == 0 and r["errores"][0][0] == 3


def test_importar_validaciones_generales(conn, admin, empleado, tmp_path):
    with pytest.raises(ErrorAcceso):
        carga_inicial.importar(conn, empleado, "clientes", tmp_path / "x.csv")
    with pytest.raises(ErrorNegocio):  # faltan columnas
        carga_inicial.importar(conn, admin, "servicios", _csv(tmp_path / "f.csv", [["nombre"], ["Algo"]]))
    with pytest.raises(ErrorNegocio):
        carga_inicial.importar(conn, admin, "inventado", tmp_path / "x.csv")
    with pytest.raises(ErrorNegocio):  # solo encabezado
        carga_inicial.importar(conn, admin, "clientes", _csv(tmp_path / "v.csv", [["nombre"]]))


def test_generar_plantilla(tmp_path):
    ruta = carga_inicial.generar_plantilla("servicios", tmp_path / "plantilla_servicios.csv")
    assert ruta.read_text(encoding="utf-8-sig").strip() == "categoria,nombre,unidad,precio"
