"""Datos del «Panel del negocio»: cómo van las ventas, los mejores clientes y los servicios que más venden.

Ventas = total de las órdenes recibidas (sin canceladas), por la fecha en que se recibieron.
Cobros = dinero que entró, por la fecha del pago (incluye anticipos y descuenta reembolsos).
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from .comunes import CERO
from .reportes import _consulta, _rango

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MESES_LARGOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
                "octubre", "noviembre", "diciembre"]


def _vendido(conn, desde: date, hasta: date) -> tuple[Decimal, int]:
    f = _consulta(conn, "SELECT COALESCE(SUM(total),0) AS v, COUNT(*) AS n FROM ordenes "
                        "WHERE estado <> 'cancelada' AND DATE(fecha_recepcion) BETWEEN %s AND %s", (desde, hasta))[0]
    return Decimal(f["v"]), int(f["n"])


def _mes_anterior(d: date) -> date:
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)


def _mismo_dia(primero: date, dia: int) -> date:
    return primero.replace(day=min(dia, calendar.monthrange(primero.year, primero.month)[1]))


def variacion(actual: Decimal, anterior: Decimal) -> Decimal | None:
    """Porcentaje de cambio contra el periodo anterior; None si antes no hubo ventas."""
    if not anterior:
        return None
    return ((actual - anterior) * 100 / anterior).quantize(Decimal("0.1"))


def resumen(conn, hoy: date | None = None) -> dict:
    """Hoy, esta semana y este mes, cada uno contra el mismo tramo del periodo anterior."""
    hoy = hoy or date.today()
    lunes = hoy - timedelta(days=hoy.weekday())
    primero = hoy.replace(day=1)
    previo = _mes_anterior(hoy)
    tramos = {
        "hoy": ((hoy, hoy), (hoy - timedelta(days=1), hoy - timedelta(days=1))),
        "semana": ((lunes, hoy), (lunes - timedelta(days=7), hoy - timedelta(days=7))),
        "mes": ((primero, hoy), (previo, _mismo_dia(previo, hoy.day))),
    }
    r = {}
    for clave, (act, ant) in tramos.items():
        v, n = _vendido(conn, *act)
        va, _ = _vendido(conn, *ant)
        r[clave] = {"vendido": v, "ordenes": n, "anterior": va, "variacion": variacion(v, va)}
    r["por_cobrar"] = Decimal(_consulta(conn, "SELECT COALESCE(SUM(saldo),0) AS s FROM v_saldo_ordenes "
                                              "WHERE saldo > 0 AND estado <> 'cancelada'")[0]["s"])
    return r


def ventas_por_mes(conn, meses: int = 12, hoy: date | None = None) -> list[dict]:
    """Los últimos `meses` meses (incluido el actual), también los que no tuvieron ventas."""
    hoy = hoy or date.today()
    inicio = hoy.replace(day=1)
    for _ in range(meses - 1):
        inicio = _mes_anterior(inicio)
    datos = {(int(f["a"]), int(f["m"])): f for f in _consulta(
        conn, "SELECT YEAR(fecha_recepcion) AS a, MONTH(fecha_recepcion) AS m, SUM(total) AS v, COUNT(*) AS n "
              "FROM ordenes WHERE estado <> 'cancelada' AND fecha_recepcion >= %s GROUP BY a, m", (inicio,))}
    filas, d = [], inicio
    for _ in range(meses):
        f = datos.get((d.year, d.month))
        filas.append({"mes": d, "etiqueta": f"{MESES[d.month - 1]} {d.year % 100:02d}",
                      "vendido": Decimal(f["v"]) if f else CERO, "ordenes": int(f["n"]) if f else 0})
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return filas


def mejor_mes(filas: list[dict]) -> dict | None:
    con_ventas = [f for f in filas if f["vendido"] > 0]
    return max(con_ventas, key=lambda f: f["vendido"]) if con_ventas else None


def acumulado_del_mes(conn, hoy: date | None = None) -> dict:
    """Ventas acumuladas día por día: este mes (hasta hoy) contra el mes anterior completo."""
    hoy = hoy or date.today()

    def serie(primero: date, ultimo_dia: int) -> list[Decimal]:
        por_dia = {int(f["d"]): Decimal(f["v"]) for f in _consulta(
            conn, "SELECT DAY(fecha_recepcion) AS d, SUM(total) AS v FROM ordenes WHERE estado <> 'cancelada' "
                  "AND DATE(fecha_recepcion) BETWEEN %s AND %s GROUP BY d", (primero, primero.replace(day=ultimo_dia)))}
        total, acum = CERO, []
        for dia in range(1, ultimo_dia + 1):
            total += por_dia.get(dia, CERO)
            acum.append(total)
        return acum

    previo = _mes_anterior(hoy)
    return {"actual": serie(hoy.replace(day=1), hoy.day),
            "anterior": serie(previo, calendar.monthrange(previo.year, previo.month)[1]),
            "nombre_actual": MESES_LARGOS[hoy.month - 1], "nombre_anterior": MESES_LARGOS[previo.month - 1]}


def clientes_top(conn, desde, hasta, limite: int = 8) -> list[dict]:
    d, h = _rango(desde, hasta)
    return [{"cliente": f["cliente"], "telefono": f["telefono"], "ordenes": int(f["n"]), "total": Decimal(f["t"])}
            for f in _consulta(
                conn, "SELECT CONCAT_WS(' ', c.nombre, c.apellidos) AS cliente, c.telefono, COUNT(*) AS n, "
                      "SUM(o.total) AS t FROM ordenes o JOIN clientes c ON c.id = o.cliente_id "
                      "WHERE o.estado <> 'cancelada' AND DATE(o.fecha_recepcion) BETWEEN %s AND %s "
                      "GROUP BY c.id, cliente, c.telefono ORDER BY n DESC, t DESC LIMIT %s", (d, h, int(limite)))]


def servicios_top(conn, desde, hasta, limite: int = 8) -> list[dict]:
    d, h = _rango(desde, hasta)
    return [{"servicio": f["servicio"], "unidad": f["unidad"], "cantidad": Decimal(f["c"]), "importe": Decimal(f["i"])}
            for f in _consulta(
                conn, "SELECT servicio, unidad, SUM(cantidad_total) AS c, SUM(importe_total) AS i "
                      "FROM v_ventas_por_servicio WHERE fecha BETWEEN %s AND %s GROUP BY servicio_id, servicio, unidad "
                      "ORDER BY i DESC LIMIT %s", (d, h, int(limite)))]


def cobros_por_metodo(conn, desde, hasta) -> list[dict]:
    d, h = _rango(desde, hasta)
    return [{"metodo": f["metodo_pago"], "total": Decimal(f["t"])} for f in _consulta(
        conn, "SELECT metodo_pago, SUM(total_cobrado) AS t FROM v_ventas_diarias WHERE fecha BETWEEN %s AND %s "
              "GROUP BY metodo_pago HAVING t > 0 ORDER BY t DESC", (d, h))]
