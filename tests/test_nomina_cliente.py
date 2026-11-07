"""Reglas de nómina tal como las respondió el cliente: pago por día a salario mínimo, hora extra fija
autorizada por la encargada, pago semanal en efectivo o transferencia, recibo firmado."""
from datetime import date, datetime
from decimal import Decimal

import pytest

from oceanica.servicios import caja, configuracion, empleados, nomina
from oceanica.servicios.comunes import ErrorNegocio

D = Decimal
MINIMO = D("315.04")


def dt(dia, h, m=0):
    return datetime(2026, 11, dia, h, m)


@pytest.fixture()
def hoy_fijo(monkeypatch):
    monkeypatch.setattr(nomina, "hoy", lambda: date(2026, 11, 16))  # lunes siguiente a la semana 2-8


def _empleado(conn, admin, nombre, dias_turno, entrada="09:00", salida="15:00"):
    eid = empleados.crear_empleado(conn, admin, nombre, "Prueba", "2026-01-01")
    empleados.definir_turnos(conn, admin, eid, [(d, entrada, salida) for d in dias_turno], "2026-01-01")
    return eid


def _trabajar(conn, admin, eid, dias, entrada=(9, 0), salida=(15, 0)):
    for d in dias:
        empleados.corregir_asistencia(conn, admin, eid, f"2026-11-{d:02d}", dt(d, *entrada), dt(d, *salida), "Captura")


def test_valores_por_omision_de_la_migracion(conn):
    cfg = configuracion.obtener_todo(conn)
    assert cfg["nomina_salario_minimo_diario"] == "315.04" and cfg["nomina_pago_hora_extra"] == "50"
    assert cfg["horas_extra_automaticas"] == "no" and cfg["asistencia_paga_justificada"] == "no"
    assert cfg["entrega_transferencia_pendiente"] == "admin" and cfg["descuento_max_pct_empleado"] == "0"


def test_salario_minimo_se_aplica_solo_a_quien_no_tiene_sueldo(conn, admin):
    a = _empleado(conn, admin, "Ana", [1, 2, 3])
    b = _empleado(conn, admin, "Beto", [4, 5, 6])
    nomina.fijar_salario(conn, admin, b, "dia", 400, "2026-01-01")
    assert nomina.aplicar_salario_minimo(conn, admin) == 1
    assert nomina.aplicar_salario_minimo(conn, admin) == 0
    assert nomina._salario_en  # sueldo de Ana existe
    assert nomina.historial_salarios(conn, admin, a)[0]["monto"] == MINIMO
    assert nomina.historial_salarios(conn, admin, b)[0]["monto"] == D("400.00")


def test_semana_se_paga_por_dia_trabajado_sabado_igual(conn, admin, hoy_fijo):
    ana = _empleado(conn, admin, "Ana", [1, 2, 3, 4, 5, 6])
    nomina.aplicar_salario_minimo(conn, admin)
    _trabajar(conn, admin, ana, [2, 3, 4, 5])                      # lunes a jueves, 6 h
    _trabajar(conn, admin, ana, [7], (9, 0), (17, 0))              # sábado de 8 h: mismo pago
    # viernes (6) no vino: no se paga y tampoco se descuenta nada
    pid = nomina.crear_periodo_semanal(conn, admin, date(2026, 11, 4))
    assert nomina.crear_periodo_semanal(conn, admin, date(2026, 11, 6)) == pid  # misma semana, mismo periodo
    r = nomina.calcular_periodo(conn, admin, pid)
    n = nomina.obtener_periodo(conn, admin, pid)["nominas"][0]
    assert n["dias_trabajados"] == D("5.00") and n["neto"] == MINIMO * 5
    assert n["total_deducciones"] == 0
    assert any("sin registro en días de trabajo" in a and "06/11" in a for a in r["advertencias"])


def test_descanso_distinto_por_empleado_no_genera_avisos(conn, admin, hoy_fijo):
    luis = _empleado(conn, admin, "Luis", [1, 2, 3, 4, 5])  # descansa sábado
    nomina.aplicar_salario_minimo(conn, admin)
    _trabajar(conn, admin, luis, [2, 3, 4, 5, 6])
    pid = nomina.crear_periodo_semanal(conn, admin, date(2026, 11, 2))
    assert nomina.calcular_periodo(conn, admin, pid)["advertencias"] == []


def test_retardo_se_registra_pero_no_descuenta(conn, admin, hoy_fijo):
    eid = _empleado(conn, admin, "Rita", [1, 2])
    nomina.aplicar_salario_minimo(conn, admin)
    _trabajar(conn, admin, eid, [2], (9, 45), (15, 0))
    a = empleados.listar_asistencias(conn, "2026-11-02", "2026-11-02", eid)[0]
    assert a["estado"] == "retardo" and a["minutos_retardo"] == 45
    _trabajar(conn, admin, eid, [3])
    pid = nomina.crear_periodo_semanal(conn, admin, date(2026, 11, 2))
    nomina.calcular_periodo(conn, admin, pid)
    n = nomina.obtener_periodo(conn, admin, pid)["nominas"][0]
    assert n["neto"] == MINIMO * 2 and n["total_deducciones"] == 0


def test_falta_justificada_no_se_paga(conn, admin, hoy_fijo):
    eid = _empleado(conn, admin, "Rita", [1, 2])
    nomina.aplicar_salario_minimo(conn, admin)
    _trabajar(conn, admin, eid, [2])
    empleados.marcar_estado(conn, admin, eid, "2026-11-03", "justificada", "Enfermedad")
    pid = nomina.crear_periodo_semanal(conn, admin, date(2026, 11, 2))
    nomina.calcular_periodo(conn, admin, pid)
    assert nomina.obtener_periodo(conn, admin, pid)["nominas"][0]["neto"] == MINIMO


def test_hora_extra_solo_si_la_autoriza_la_encargada_a_50_pesos(conn, admin, empleado, hoy_fijo):
    eid = _empleado(conn, admin, "Ana", [1, 2, 3])
    nomina.aplicar_salario_minimo(conn, admin)
    # se queda dos horas más, pero nadie lo autoriza: no se paga
    r = empleados.registrar_entrada(conn, empleado, eid, dt(2, 9, 0))
    r = empleados.registrar_salida(conn, empleado, eid, dt(2, 17, 0))
    assert r["horas_extra"] == D("0.00")
    pid = nomina.crear_periodo_semanal(conn, admin, date(2026, 11, 2))
    nomina.calcular_periodo(conn, admin, pid)
    assert nomina.obtener_periodo(conn, admin, pid)["nominas"][0]["neto"] == MINIMO

    with pytest.raises(Exception):  # un empleado no puede autorizarse horas extra
        empleados.autorizar_horas_extra(conn, empleado, eid, "2026-11-02", 2, "x")
    with pytest.raises(ErrorNegocio):  # día sin asistencia
        empleados.autorizar_horas_extra(conn, admin, eid, "2026-11-03", 2, "x")
    with pytest.raises(ErrorNegocio):  # demasiadas horas
        empleados.autorizar_horas_extra(conn, admin, eid, "2026-11-02", 9, "x")
    empleados.autorizar_horas_extra(conn, admin, eid, "2026-11-02", 2, "Autoriza Ara: entrega urgente")
    nomina.calcular_periodo(conn, admin, pid)
    n = nomina.obtener_periodo(conn, admin, pid)["nominas"][0]
    assert n["neto"] == MINIMO + 100  # 2 h x $50
    # corregir la hora de salida no borra lo autorizado
    empleados.corregir_asistencia(conn, admin, eid, "2026-11-02", dt(2, 9, 0), dt(2, 16, 30), "Ajuste")
    assert empleados.listar_asistencias(conn, "2026-11-02", "2026-11-02", eid)[0]["horas_extra"] == D("2.00")


def test_pago_en_efectivo_sale_de_caja_y_por_transferencia_no(conn, admin, hoy_fijo):
    a = _empleado(conn, admin, "Ana", [1, 2])
    b = _empleado(conn, admin, "Beto", [1, 2])
    nomina.aplicar_salario_minimo(conn, admin)
    _trabajar(conn, admin, a, [2, 3])
    _trabajar(conn, admin, b, [2, 3])
    pid = nomina.crear_periodo_semanal(conn, admin, date(2026, 11, 2))
    nomina.calcular_periodo(conn, admin, pid)
    nomina.aprobar_periodo(conn, admin, pid)
    por = {n["empleado"]: n["id"] for n in nomina.obtener_periodo(conn, admin, pid)["nominas"]}
    with pytest.raises(ErrorNegocio):
        nomina.registrar_pago_empleado(conn, admin, por["Ana Prueba"], True, "efectivo")  # sin caja abierta
    caja.abrir_corte(conn, admin, 3000)
    nomina.registrar_pago_empleado(conn, admin, por["Ana Prueba"], True, "efectivo", recibo_firmado=True)
    assert caja.resumen_corte(conn)["gastos"] == MINIMO * 2
    nomina.registrar_pago_empleado(conn, admin, por["Beto Prueba"], True, "transferencia")
    assert caja.resumen_corte(conn)["gastos"] == MINIMO * 2  # la transferencia no toca la caja
    p = {n["empleado"]: n for n in nomina.obtener_periodo(conn, admin, pid)["nominas"]}
    assert (p["Ana Prueba"]["metodo_pago"], p["Ana Prueba"]["recibo_firmado"]) == ("efectivo", 1)
    assert (p["Beto Prueba"]["metodo_pago"], p["Beto Prueba"]["recibo_firmado"]) == ("transferencia", 0)
    nomina.marcar_recibo_firmado(conn, admin, por["Beto Prueba"])
    assert nomina.obtener_periodo(conn, admin, pid)["nominas"][1]["recibo_firmado"] == 1
    with pytest.raises(ErrorNegocio):
        nomina.registrar_pago_empleado(conn, admin, por["Ana Prueba"], True, "bitcoin")


def test_quien_no_trabajo_la_semana_no_bloquea_el_cierre(conn, admin, hoy_fijo):
    a = _empleado(conn, admin, "Ana", [1, 2])
    _empleado(conn, admin, "Beto", [1, 2])                      # no trabajó nada: neto $0
    nomina.aplicar_salario_minimo(conn, admin)
    _trabajar(conn, admin, a, [2])
    pid = nomina.crear_periodo_semanal(conn, admin, date(2026, 11, 2))
    nomina.calcular_periodo(conn, admin, pid)
    nomina.aprobar_periodo(conn, admin, pid)
    por = {n["empleado"]: n for n in nomina.obtener_periodo(conn, admin, pid)["nominas"]}
    assert por["Beto Prueba"]["neto"] == 0
    with pytest.raises(ErrorNegocio):
        nomina.registrar_pago_empleado(conn, admin, por["Beto Prueba"]["id"])
    with pytest.raises(ErrorNegocio, match="Faltan 1"):
        nomina.cerrar_periodo(conn, admin, pid)
    nomina.registrar_pago_empleado(conn, admin, por["Ana Prueba"]["id"], False, "transferencia")
    nomina.cerrar_periodo(conn, admin, pid)
    assert nomina.obtener_periodo(conn, admin, pid)["estado"] == "cerrado"
