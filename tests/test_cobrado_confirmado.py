"""Regla del cliente: una transferencia queda «por confirmar» hasta que la encargada la revisa en el banco, así que
no cuenta como «cobrado» en reportes ni en el Panel hasta entonces; una rechazada no cuenta nunca (migración 014)."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from oceanica.servicios import caja, catalogo, ordenes, reportes

from .test_app import _sin_dialogos, qapp  # noqa: F401  (fixture de Qt)

D = Decimal
AYER, HOY = date.today() - timedelta(days=1), date.today()


@pytest.fixture()
def negocio(conn, admin, empleado):
    cat = catalogo.listar_categorias(conn)[0]["id"]
    sid = catalogo.crear_servicio(conn, admin, cat, "Edredón", "pieza", "100")
    caja.abrir_corte(conn, admin, 0)
    metodos = {m["nombre"]: m["id"] for m in caja.listar_metodos(conn)}
    return {"sid": sid, "efectivo": metodos["Efectivo"], "transferencia": metodos["Transferencia"]}


def _orden_pagada(conn, empleado, negocio, metodo, ref=None, cuando=None):
    oid = ordenes.crear_orden(conn, empleado, [{"servicio_id": negocio["sid"], "cantidad": 1}])
    pid = caja.registrar_pago(conn, empleado, oid, negocio[metodo], D("100"), referencia=ref)
    if cuando:  # el cobro fue otro día
        cur = conn.cursor()
        cur.execute("UPDATE pagos SET pagado_en = %s WHERE id = %s", (cuando, pid))
        conn.commit()
        cur.close()
    return oid, pid


def _cobrado(conn, desde, hasta):
    return reportes.resumen_general(conn, desde, hasta)["cobrado"]


def test_pendiente_no_cuenta_y_confirmada_si(conn, admin, empleado, negocio):
    _orden_pagada(conn, empleado, negocio, "efectivo")
    _, pid = _orden_pagada(conn, empleado, negocio, "transferencia", "CAPTURA DE PANTALLA")
    r = reportes.resumen_general(conn, HOY, HOY)
    assert r["cobrado"] == D("100.00") and r["por_confirmar"] == D("100.00")     # solo el efectivo es dinero seguro
    assert reportes.ventas_por_dia(conn, HOY, HOY)["totales"]["cobrado"] == D("100.00")
    assert {f["metodo_pago"] for f in reportes.cobros_por_metodo(conn, HOY, HOY)["filas"]} == {"Efectivo"}

    caja.confirmar_transferencia(conn, admin, pid)                                 # la encargada la vio en el banco
    r = reportes.resumen_general(conn, HOY, HOY)
    assert r["cobrado"] == D("200.00") and r["por_confirmar"] == D("0.00")
    assert {f["metodo_pago"]: D(f["total"]) for f in reportes.cobros_por_metodo(conn, HOY, HOY)["filas"]} == {
        "Efectivo": D("100.00"), "Transferencia": D("100.00")}


def test_rechazada_no_infla_ningun_dia(conn, admin, empleado, negocio):
    ayer = datetime.combine(AYER, datetime.min.time()).replace(hour=11)
    oid, pid = _orden_pagada(conn, empleado, negocio, "transferencia", "MBAN-1", cuando=ayer)
    caja.rechazar_transferencia(conn, admin, pid, "No llegó al banco")             # el contraasiento queda hoy
    assert _cobrado(conn, AYER, AYER) == 0 and _cobrado(conn, HOY, HOY) == 0       # antes: +100 ayer y -100 hoy
    assert reportes.resumen_general(conn, AYER, HOY)["por_confirmar"] == 0
    assert ordenes.obtener_orden(conn, oid)["saldo"] == D("100.00")                # la orden recupera su saldo


def test_reportes_avisa_cuanto_hay_por_confirmar(qapp, conn, admin, empleado, negocio, monkeypatch):
    from oceanica.app import v_reportes
    from oceanica.app.contexto import Contexto
    _sin_dialogos(monkeypatch)
    ctx = Contexto(conn)
    ctx.admin = admin
    vista = v_reportes.ReportesView(ctx)
    vista.al_mostrar()
    assert "por confirmar" not in vista.lb_alerta.text()
    _orden_pagada(conn, empleado, negocio, "transferencia", "CAPTURA DE PANTALLA")
    vista.recargar()
    assert "$100.00 en transferencias por confirmar" in vista.lb_alerta.text()
    assert vista.kpi["cobrado"].text() == "$0.00"
    vista.close()
