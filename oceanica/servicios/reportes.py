"""Reportes y métricas. Cada reporte devuelve un dict:
    {'titulo', 'subtitulo', 'columnas': [(clave, encabezado, tipo)], 'filas': [dict], 'totales': {clave: valor}}
con tipo en: texto, dinero, numero, fecha, fechahora. Ese formato lo consumen la pantalla y las exportaciones.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from ..db import transaccion
from .comunes import CERO, como_fecha, config_valor, requerir_rol
from . import facturacion
from . import nomina as svc_nomina


def _rango(desde, hasta) -> tuple[date, date]:
    d, h = como_fecha(desde, "desde"), como_fecha(hasta, "hasta")
    if h < d:
        d, h = h, d
    return d, h


def _reporte(titulo, columnas, filas, subtitulo="", sumar=()):
    totales = {c: sum((Decimal(f[c] or 0) for f in filas), CERO) for c in sumar}
    return {"titulo": titulo, "subtitulo": subtitulo, "columnas": columnas, "filas": filas, "totales": totales}


def _consulta(conn, sql, params=()):
    with transaccion(conn) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def ventas_por_dia(conn, desde, hasta) -> dict:
    """Por fecha: órdenes recibidas, total vendido y dinero cobrado (el cobro puede ser otro día)."""
    d, h = _rango(desde, hasta)
    vendido = {f["fecha"]: f for f in _consulta(
        conn, "SELECT DATE(fecha_recepcion) AS fecha, COUNT(*) AS ordenes, SUM(total) AS vendido FROM ordenes "
              "WHERE estado <> 'cancelada' AND DATE(fecha_recepcion) BETWEEN %s AND %s GROUP BY DATE(fecha_recepcion)", (d, h))}
    cobrado = {f["fecha"]: Decimal(f["total_cobrado"]) for f in _consulta(
        conn, "SELECT fecha, SUM(total_cobrado) AS total_cobrado FROM v_ventas_diarias WHERE fecha BETWEEN %s AND %s "
              "GROUP BY fecha", (d, h))}
    filas = []
    for fecha in sorted(set(vendido) | set(cobrado)):
        v = vendido.get(fecha)
        filas.append({"fecha": fecha, "ordenes": int(v["ordenes"]) if v else 0,
                      "vendido": Decimal(v["vendido"]) if v else CERO, "cobrado": cobrado.get(fecha, CERO)})
    cols = [("fecha", "Fecha", "fecha"), ("ordenes", "Órdenes", "numero"),
            ("vendido", "Vendido", "dinero"), ("cobrado", "Cobrado", "dinero")]
    r = _reporte("Ventas por día", cols, filas, f"Del {d} al {h}", ("ordenes", "vendido", "cobrado"))
    return r


_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre"]


def _ventas_agrupadas(conn, d: date, h: date, clave_de) -> dict:
    """Órdenes y vendido por fecha de recepción, cobrado por fecha de pago, sumados según clave_de(fecha)."""
    grupos: dict = {}

    def grupo(fecha):
        return grupos.setdefault(clave_de(fecha), {"ordenes": 0, "vendido": CERO, "cobrado": CERO})

    for f in _consulta(conn, "SELECT DATE(fecha_recepcion) AS fecha, COUNT(*) AS n, SUM(total) AS v FROM ordenes "
                             "WHERE estado <> 'cancelada' AND DATE(fecha_recepcion) BETWEEN %s AND %s "
                             "GROUP BY DATE(fecha_recepcion)", (d, h)):
        g = grupo(f["fecha"])
        g["ordenes"] += int(f["n"])
        g["vendido"] += Decimal(f["v"])
    for f in _consulta(conn, "SELECT fecha, SUM(total_cobrado) AS t FROM v_ventas_diarias WHERE fecha BETWEEN %s AND %s "
                             "GROUP BY fecha", (d, h)):
        grupo(f["fecha"])["cobrado"] += Decimal(f["t"])
    return grupos


def _cols_agrupadas(primera: tuple) -> list:
    return [primera, ("ordenes", "Órdenes", "numero"), ("vendido", "Vendido", "dinero"),
            ("promedio", "Promedio por orden", "dinero"), ("cobrado", "Cobrado", "dinero")]


def _promedio(vendido: Decimal, ordenes: int) -> Decimal:
    return (vendido / ordenes).quantize(Decimal("0.01")) if ordenes else CERO


def _con_promedio(r: dict) -> dict:
    """El total de «Promedio por orden» es el promedio de todo el periodo, no una suma."""
    t = r["totales"]
    t["promedio"] = _promedio(t["vendido"], int(t["ordenes"]))
    return r


def ventas_por_semana(conn, desde, hasta) -> dict:
    """Semanas de lunes a domingo: órdenes, vendido, promedio por orden y cobrado."""
    d, h = _rango(desde, hasta)
    grupos = _ventas_agrupadas(conn, d, h, lambda f: f - timedelta(days=f.weekday()))
    filas = []
    for lunes in sorted(grupos):
        domingo = lunes + timedelta(days=6)
        if lunes.month == domingo.month:
            texto = f"Del {lunes.day} al {domingo.day} de {_MESES[lunes.month - 1]} {lunes.year}"
        else:
            texto = f"Del {lunes.day} de {_MESES[lunes.month - 1]} al {domingo.day} de {_MESES[domingo.month - 1]} {domingo.year}"
        g = grupos[lunes]
        filas.append({"semana": texto, **g, "promedio": _promedio(g["vendido"], g["ordenes"])})
    return _con_promedio(_reporte("Ventas por semana", _cols_agrupadas(("semana", "Semana (lunes a domingo)", "texto")),
                                  filas, f"Del {d} al {h}", ("ordenes", "vendido", "cobrado")))


def ventas_por_mes(conn, desde, hasta) -> dict:
    """Meses: órdenes, vendido, promedio por orden y cobrado."""
    d, h = _rango(desde, hasta)
    grupos = _ventas_agrupadas(conn, d, h, lambda f: (f.year, f.month))
    filas = []
    for (anio, mes) in sorted(grupos):
        g = grupos[(anio, mes)]
        filas.append({"mes": f"{_MESES[mes - 1].capitalize()} {anio}", **g, "promedio": _promedio(g["vendido"], g["ordenes"])})
    return _con_promedio(_reporte("Ventas por mes", _cols_agrupadas(("mes", "Mes", "texto")), filas, f"Del {d} al {h}",
                                  ("ordenes", "vendido", "cobrado")))


def cobros_por_metodo(conn, desde, hasta) -> dict:
    d, h = _rango(desde, hasta)
    filas = _consulta(conn, "SELECT metodo_pago, SUM(num_pagos) AS pagos, SUM(total_cobrado) AS total "
                            "FROM v_ventas_diarias WHERE fecha BETWEEN %s AND %s GROUP BY metodo_pago ORDER BY total DESC",
                      (d, h))
    cols = [("metodo_pago", "Método de pago", "texto"), ("pagos", "Pagos", "numero"), ("total", "Total", "dinero")]
    return _reporte("Cobros por método de pago", cols, filas, f"Del {d} al {h}", ("pagos", "total"))


def ventas_por_servicio(conn, desde, hasta) -> dict:
    d, h = _rango(desde, hasta)
    filas = _consulta(
        conn, "SELECT servicio, categoria, unidad, SUM(cantidad_total) AS cantidad, SUM(importe_total) AS importe "
              "FROM v_ventas_por_servicio WHERE fecha BETWEEN %s AND %s GROUP BY servicio_id, servicio, categoria, unidad "
              "ORDER BY importe DESC", (d, h))
    cols = [("servicio", "Servicio", "texto"), ("categoria", "Categoría", "texto"), ("unidad", "Unidad", "texto"),
            ("cantidad", "Cantidad", "numero"), ("importe", "Importe", "dinero")]
    return _reporte("Ventas por servicio", cols, filas, f"Del {d} al {h}", ("importe",))


def ordenes_pendientes(conn) -> dict:
    filas = _consulta(
        conn, "SELECT p.folio, p.cliente, p.telefono, p.estado, p.fecha_recepcion, p.fecha_promesa, p.dias_retraso, "
              "p.total, s.saldo FROM v_ordenes_pendientes p JOIN v_saldo_ordenes s ON s.orden_id = p.orden_id "
              "ORDER BY p.dias_retraso DESC, p.fecha_promesa")
    cols = [("folio", "Folio", "texto"), ("cliente", "Cliente", "texto"), ("telefono", "Teléfono", "texto"),
            ("estado", "Estado", "texto"), ("fecha_promesa", "Promesa", "fechahora"),
            ("dias_retraso", "Días de retraso", "numero"), ("total", "Total", "dinero"), ("saldo", "Saldo", "dinero")]
    return _reporte("Órdenes pendientes", cols, filas, "Órdenes recibidas, en proceso o listas", ("total", "saldo"))


def ropa_olvidada(conn) -> dict:
    """Órdenes listas que llevan esperando más días de los configurados («almacenaje_dias», 30 por omisión).
    Los días cuentan desde que la orden se marcó como lista, no desde que se recibió."""
    with transaccion(conn) as cur:
        try:
            limite = max(0, int(float(config_valor(cur, "almacenaje_dias", "30") or 30)))
        except ValueError:
            limite = 30
    filas = _consulta(
        conn, "SELECT o.folio, CONCAT_WS(' ', c.nombre, c.apellidos) AS cliente, c.telefono, h.lista_desde, "
              "DATEDIFF(CURDATE(), h.lista_desde) AS dias, o.total, s.saldo, o.avisado_en "
              "FROM ordenes o JOIN v_saldo_ordenes s ON s.orden_id = o.id "
              "JOIN (SELECT orden_id, MAX(cambiado_en) AS lista_desde FROM orden_historial_estado "
              "      WHERE estado_nuevo = 'lista' GROUP BY orden_id) h ON h.orden_id = o.id "
              "LEFT JOIN clientes c ON c.id = o.cliente_id "
              "WHERE o.estado = 'lista' AND DATEDIFF(CURDATE(), h.lista_desde) >= %s "
              "ORDER BY h.lista_desde", (limite,))
    cols = [("folio", "Folio", "texto"), ("cliente", "Cliente", "texto"), ("telefono", "Teléfono", "texto"),
            ("lista_desde", "Lista desde", "fecha"), ("dias", "Días esperando", "numero"),
            ("total", "Total", "dinero"), ("saldo", "Por cobrar", "dinero"), ("avisado_en", "Último aviso", "fechahora")]
    return _reporte("Ropa olvidada", cols, filas, f"Órdenes listas con {limite} días o más sin recoger",
                    ("total", "saldo"))


def entregas_domicilio(conn) -> dict:
    """Ruta de reparto: órdenes a domicilio sin entregar, primero las que ya están listas."""
    filas = _consulta(
        conn, "SELECT o.folio, CONCAT_WS(' ', c.nombre, c.apellidos) AS cliente, c.telefono, o.direccion_entrega, "
              "CASE o.estado WHEN 'lista' THEN 'Lista' WHEN 'en_proceso' THEN 'En proceso' ELSE 'Recibida' END AS estado, "
              "o.fecha_promesa, s.saldo "
              "FROM ordenes o JOIN v_saldo_ordenes s ON s.orden_id = o.id LEFT JOIN clientes c ON c.id = o.cliente_id "
              "WHERE o.tipo_entrega = 'domicilio' AND o.estado IN ('recibida', 'en_proceso', 'lista') "
              "ORDER BY (o.estado = 'lista') DESC, o.fecha_promesa, o.id")
    cols = [("folio", "Folio", "texto"), ("cliente", "Cliente", "texto"), ("telefono", "Teléfono", "texto"),
            ("direccion_entrega", "Dirección", "texto"), ("estado", "Estado", "texto"),
            ("fecha_promesa", "Promesa", "fechahora"), ("saldo", "Por cobrar", "dinero")]
    return _reporte("Entregas a domicilio", cols, filas, "Órdenes a domicilio pendientes de entregar", ("saldo",))


def transferencias_pendientes(conn, sesion) -> dict:
    """Transferencias cobradas que el administrador aún no confirma contra el banco."""
    requerir_rol(sesion, "administrador")
    filas = _consulta(
        conn, "SELECT o.folio, p.pagado_en, p.monto, p.referencia, u.usuario AS cobro, o.estado AS estado_orden "
              "FROM pagos p JOIN ordenes o ON o.id = p.orden_id JOIN usuarios u ON u.id = p.usuario_id "
              "WHERE p.estado_confirmacion = 'pendiente' ORDER BY p.pagado_en")
    cols = [("folio", "Folio", "texto"), ("pagado_en", "Fecha", "fechahora"), ("monto", "Monto", "dinero"),
            ("referencia", "Clave de rastreo", "texto"), ("cobro", "Cobró", "texto"), ("estado_orden", "Orden", "texto")]
    return _reporte("Transferencias por confirmar", cols, filas, "Pendientes de verificar en el banco", ("monto",))


def por_facturar(conn, sesion, desde, hasta) -> dict:
    """Órdenes que pidieron factura y todavía no se marcan como facturadas, recibidas hasta `hasta`.

    Incluye las de meses anteriores que siguen pendientes (columna «Periodo» = «Anterior»): si solo se
    mostraran las del mes, una factura olvidada desaparecería del reporte al cambiar de mes."""
    requerir_rol(sesion, "administrador")
    d, h = _rango(desde, hasta)
    filas = _consulta(
        conn, "SELECT o.folio, o.fecha_recepcion, o.estado, CONCAT_WS(' ', c.nombre, c.apellidos) AS cliente, "
              "c.rfc, c.razon_social, c.regimen_fiscal, c.uso_cfdi, c.codigo_postal_fiscal, c.email, o.total, "
              "s.pagado, s.saldo FROM ordenes o JOIN clientes c ON c.id = o.cliente_id "
              "JOIN v_saldo_ordenes s ON s.orden_id = o.id "
              "WHERE o.requiere_factura = 1 AND o.facturada = 0 AND o.estado <> 'cancelada' "
              "AND DATE(o.fecha_recepcion) <= %s ORDER BY o.fecha_recepcion, o.id", (h,))
    for f in filas:
        f["periodo"] = "Anterior" if f["fecha_recepcion"].date() < d else "Del periodo"
        falta = facturacion.faltantes(f)
        f["datos"] = "Completos" if not falta else "Falta: " + ", ".join(falta)
    cols = [("folio", "Folio", "texto"), ("fecha_recepcion", "Recibida", "fechahora"), ("periodo", "Periodo", "texto"),
            ("cliente", "Cliente", "texto"), ("rfc", "RFC", "texto"), ("razon_social", "Razón social", "texto"),
            ("regimen_fiscal", "Régimen", "texto"), ("uso_cfdi", "Uso CFDI", "texto"),
            ("codigo_postal_fiscal", "C.P.", "texto"), ("email", "Correo", "texto"), ("datos", "Datos fiscales", "texto"),
            ("total", "Total", "dinero"), ("pagado", "Pagado", "dinero"), ("saldo", "Saldo", "dinero")]
    return _reporte("Órdenes por facturar", cols, filas,
                    f"Pendientes recibidas del {d} al {h}, más las anteriores que siguen sin facturar", ("total",))


def clientes_frecuentes(conn, limite: int = 20) -> dict:
    filas = _consulta(conn, "SELECT cliente, telefono, num_ordenes, total_gastado, ultima_visita FROM v_clientes_frecuentes "
                            "ORDER BY num_ordenes DESC, total_gastado DESC LIMIT %s", (int(limite),))
    cols = [("cliente", "Cliente", "texto"), ("telefono", "Teléfono", "texto"), ("num_ordenes", "Órdenes", "numero"),
            ("total_gastado", "Total gastado", "dinero"), ("ultima_visita", "Última visita", "fechahora")]
    return _reporte("Clientes frecuentes", cols, filas, f"Los {limite} con más órdenes", ("total_gastado",))


def insumos_bajos(conn) -> dict:
    filas = _consulta(conn, "SELECT nombre, categoria, unidad, existencia, minimo, proveedor FROM v_insumos_bajos ORDER BY nombre")
    cols = [("nombre", "Insumo", "texto"), ("categoria", "Categoría", "texto"), ("unidad", "Unidad", "texto"),
            ("existencia", "Existencia", "numero"), ("minimo", "Mínimo", "numero"), ("proveedor", "Proveedor", "texto")]
    return _reporte("Insumos con poca existencia", cols, filas, "En o por debajo del mínimo")


def asistencia(conn, desde, hasta, empleado_id: int | None = None) -> dict:
    d, h = _rango(desde, hasta)
    sql = ("SELECT empleado, fecha, estado, minutos_retardo, horas_trabajadas, horas_extra FROM v_asistencia_resumen "
           "WHERE fecha BETWEEN %s AND %s")
    params: list = [d, h]
    if empleado_id:
        sql += " AND empleado_id = %s"
        params.append(empleado_id)
    filas = _consulta(conn, sql + " ORDER BY empleado, fecha", params)
    cols = [("empleado", "Empleado", "texto"), ("fecha", "Fecha", "fecha"), ("estado", "Estado", "texto"),
            ("minutos_retardo", "Min. retardo", "numero"), ("horas_trabajadas", "Horas", "numero"),
            ("horas_extra", "Horas extra", "numero")]
    return _reporte("Asistencia", cols, filas, f"Del {d} al {h}", ("horas_trabajadas", "horas_extra"))


def cortes_de_caja(conn, desde, hasta) -> dict:
    d, h = _rango(desde, hasta)
    filas = _consulta(
        conn, "SELECT c.id, c.abierta_en, c.cerrada_en, c.fondo_inicial, c.efectivo_esperado, c.efectivo_contado, "
              "c.diferencia, c.estado, ua.usuario AS abrio FROM cortes_caja c JOIN usuarios ua ON ua.id = c.usuario_apertura_id "
              "WHERE DATE(c.abierta_en) BETWEEN %s AND %s ORDER BY c.id", (d, h))
    cols = [("id", "Corte", "numero"), ("abierta_en", "Apertura", "fechahora"), ("cerrada_en", "Cierre", "fechahora"),
            ("abrio", "Abrió", "texto"), ("fondo_inicial", "Fondo", "dinero"), ("efectivo_esperado", "Esperado", "dinero"),
            ("efectivo_contado", "Contado", "dinero"), ("diferencia", "Diferencia", "dinero"), ("estado", "Estado", "texto")]
    return _reporte("Cortes de caja", cols, filas, f"Del {d} al {h}", ("diferencia",))


def nomina_periodo(conn, sesion, periodo_id: int) -> dict:
    p = svc_nomina.obtener_periodo(conn, sesion, periodo_id)  # exige rol administrador
    filas = [{"empleado": n["empleado"], "dias": n["dias_trabajados"], "horas": n["horas_trabajadas"],
              "percepciones": n["total_percepciones"], "deducciones": n["total_deducciones"], "neto": n["neto"],
              "pagado": n["pagado_en"]} for n in p["nominas"]]
    cols = [("empleado", "Empleado", "texto"), ("dias", "Días pagados", "numero"), ("horas", "Horas", "numero"),
            ("percepciones", "Percepciones", "dinero"), ("deducciones", "Deducciones", "dinero"),
            ("neto", "Neto", "dinero"), ("pagado", "Pagado el", "fechahora")]
    return _reporte(f"Nómina {p['periodicidad']}", cols, filas,
                    f"Del {p['fecha_inicio']} al {p['fecha_fin']} ({p['estado']})", ("percepciones", "deducciones", "neto"))


def costo_nomina_vs_ventas(conn, sesion, desde, hasta) -> dict:
    """Compara lo pagado de nómina (periodos que terminan en el rango) contra lo vendido en el mismo rango."""
    requerir_rol(sesion, "administrador")
    d, h = _rango(desde, hasta)
    nom = _consulta(conn, "SELECT COALESCE(SUM(n.neto),0) AS neto FROM nomina_empleado n JOIN periodos_nomina p ON p.id = n.periodo_id "
                          "WHERE p.estado IN ('aprobado','cerrado') AND p.fecha_fin BETWEEN %s AND %s", (d, h))[0]["neto"]
    ven = _consulta(conn, "SELECT COALESCE(SUM(total),0) AS v FROM ordenes WHERE estado <> 'cancelada' "
                          "AND DATE(fecha_recepcion) BETWEEN %s AND %s", (d, h))[0]["v"]
    nom, ven = Decimal(nom), Decimal(ven)
    pct = (nom * 100 / ven).quantize(Decimal("0.1")) if ven else None
    return {"desde": d, "hasta": h, "nomina": nom, "ventas": ven, "porcentaje": pct}


def resumen_general(conn, desde, hasta) -> dict:
    """Indicadores del periodo para el tablero principal."""
    d, h = _rango(desde, hasta)
    o = _consulta(conn, "SELECT COUNT(*) AS ordenes, COALESCE(SUM(total),0) AS vendido FROM ordenes "
                        "WHERE estado <> 'cancelada' AND DATE(fecha_recepcion) BETWEEN %s AND %s", (d, h))[0]
    cobrado = _consulta(conn, "SELECT COALESCE(SUM(total_cobrado),0) AS t FROM v_ventas_diarias WHERE fecha BETWEEN %s AND %s", (d, h))[0]["t"]
    kilos = _consulta(conn, "SELECT COALESCE(SUM(cantidad_total),0) AS k FROM v_ventas_por_servicio WHERE unidad = 'kilo' "
                            "AND fecha BETWEEN %s AND %s", (d, h))[0]["k"]
    nuevos = _consulta(conn, "SELECT COUNT(*) AS n FROM clientes WHERE DATE(creado_en) BETWEEN %s AND %s", (d, h))[0]["n"]
    abiertas = _consulta(conn, "SELECT COUNT(*) AS n, COALESCE(SUM(dias_retraso > 0),0) AS retrasadas FROM v_ordenes_pendientes")[0]
    por_cobrar = _consulta(conn, "SELECT COALESCE(SUM(saldo),0) AS s FROM v_saldo_ordenes WHERE saldo > 0")[0]["s"]
    n_ordenes, vendido = int(o["ordenes"]), Decimal(o["vendido"])
    return {
        "desde": d, "hasta": h, "ordenes": n_ordenes, "vendido": vendido, "cobrado": Decimal(cobrado),
        "ticket_promedio": (vendido / n_ordenes).quantize(Decimal("0.01")) if n_ordenes else CERO,
        "kilos": Decimal(kilos), "clientes_nuevos": int(nuevos), "ordenes_abiertas": int(abiertas["n"]),
        "ordenes_retrasadas": int(abiertas["retrasadas"]), "por_cobrar": Decimal(por_cobrar),
    }
