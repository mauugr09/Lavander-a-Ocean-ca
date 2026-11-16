"""Datos del Panel del negocio: ventas por mes, avance del mes, clientes y servicios principales."""
from datetime import date, datetime
from decimal import Decimal

from oceanica.servicios import caja, catalogo, clientes, ordenes, panel

D = Decimal
HOY = date(2026, 11, 16)


def _orden(conn, sesion, servicio, cantidad, cuando: datetime, cliente=None, cancelar=False):
    oid = ordenes.crear_orden(conn, sesion, [{"servicio_id": servicio, "cantidad": cantidad}], cliente)
    cur = conn.cursor()
    cur.execute("UPDATE ordenes SET fecha_recepcion = %s, fecha_promesa = %s WHERE id = %s", (cuando, cuando, oid))
    if cancelar:
        cur.execute("UPDATE ordenes SET estado = 'cancelada' WHERE id = %s", (oid,))
    conn.commit()
    return oid


def test_panel_ventas_avance_y_mejores(conn, admin, empleado):
    cats = catalogo.listar_categorias(conn)
    kilo = catalogo.crear_servicio(conn, admin, cats[0]["id"], "Lavado y secado", "kilo", "30")
    pieza = catalogo.crear_servicio(conn, admin, cats[1]["id"], "Edredón", "pieza", "150")
    ana = clientes.crear_cliente(conn, admin, "Ana", "Torres")
    luis = clientes.crear_cliente(conn, admin, "Luis", "Mora")
    _orden(conn, empleado, kilo, 10, datetime(2026, 11, 16, 10), ana)      # hoy: 300
    _orden(conn, empleado, pieza, 1, datetime(2026, 11, 15, 10), ana)     # ayer: 150
    _orden(conn, empleado, kilo, 5, datetime(2026, 11, 3, 10), luis)      # este mes: 150
    _orden(conn, empleado, pieza, 4, datetime(2026, 10, 5, 10), luis)     # octubre: 600 (antes del día 16)
    _orden(conn, empleado, kilo, 2, datetime(2026, 10, 25, 10))           # octubre: 60 (después del día 16)
    _orden(conn, empleado, pieza, 9, datetime(2026, 9, 9, 10), cancelar=True)   # cancelada: no cuenta

    r = panel.resumen(conn, HOY)
    assert r["hoy"]["vendido"] == D("300") and r["hoy"]["variacion"] == D("100.0")      # vs ayer 150
    assert r["semana"]["vendido"] == D("300")            # el 16 de noviembre de 2026 es lunes: la semana empieza hoy
    assert r["mes"]["vendido"] == D("600") and r["mes"]["anterior"] == D("600") and r["mes"]["variacion"] == D("0.0")

    meses = panel.ventas_por_mes(conn, 12, HOY)
    assert len(meses) == 12 and meses[-1]["etiqueta"] == "nov 26" and meses[0]["etiqueta"] == "dic 25"
    por = {m["etiqueta"]: m["vendido"] for m in meses}
    assert por["oct 26"] == D("660") and por["nov 26"] == D("600") and por["sep 26"] == 0
    assert panel.mejor_mes(meses)["etiqueta"] == "oct 26"

    a = panel.acumulado_del_mes(conn, HOY)
    assert len(a["actual"]) == 16 and a["actual"][-1] == D("600") and a["actual"][2] == D("150")
    assert len(a["anterior"]) == 31 and a["anterior"][-1] == D("660") and a["nombre_anterior"] == "octubre"

    top = panel.clientes_top(conn, "2026-10-01", "2026-11-30")
    # empate en visitas: primero quien ha gastado más
    assert [(c["cliente"], c["ordenes"], c["total"]) for c in top] == [("Luis Mora", 2, D("750")), ("Ana Torres", 2, D("450"))]
    serv = panel.servicios_top(conn, "2026-10-01", "2026-11-30")
    assert [s["servicio"] for s in serv] == ["Edredón", "Lavado y secado"] and serv[0]["importe"] == D("750")
    assert panel.variacion(D("50"), D("0")) is None


def test_datos_de_ejemplo_dejan_una_base_coherente(conn, admin):
    from oceanica import datos_demo
    r = datos_demo.generar(conn, dias=20)
    assert r["ordenes"] > 20 and r["clientes"] == 20 and len(r["pines"]) == 3
    assert not caja.corte_abierto(conn)                                   # la caja de ejemplo quedó cerrada
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT COUNT(*) AS n FROM cortes_caja WHERE diferencia <> 0")
    assert cur.fetchone()["n"] == 0
    cur.execute("SELECT estado, COUNT(*) AS n FROM ordenes GROUP BY estado")
    estados = {f["estado"]: f["n"] for f in cur.fetchall()}
    assert {"recibida", "en_proceso", "lista", "entregada"} <= set(estados)
    cur.execute("SELECT COUNT(*) AS n FROM v_saldo_ordenes WHERE estado = 'entregada' AND saldo <> 0")
    assert cur.fetchone()["n"] == 0                                       # lo entregado está pagado
    assert panel.resumen(conn)["mes"]["vendido"] >= 0
