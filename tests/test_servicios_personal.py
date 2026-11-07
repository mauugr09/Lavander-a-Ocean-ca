"""Integración: empleados, turnos, asistencia y nómina contra una base real."""
from datetime import date, datetime
from decimal import Decimal

import pytest

from oceanica.seguridad import ErrorAcceso
from oceanica.servicios import caja, configuracion, empleados, nomina
from oceanica.servicios.comunes import ErrorNegocio

D = Decimal
LUN_A_SAB = [(d, "09:00", "17:00") for d in range(1, 7)]


def dt(dia, h, m=0):
    return datetime(2026, 11, dia, h, m)


@pytest.fixture()
def ana(conn, admin):
    """Empleada con turno lunes a sábado 9-17 y sueldo de $3,000 por quincena."""
    eid = empleados.crear_empleado(conn, admin, "Ana", "Torres", "2026-01-01", puesto="Operadora")
    empleados.definir_turnos(conn, admin, eid, LUN_A_SAB, "2026-01-01")
    nomina.fijar_salario(conn, admin, eid, "quincena", 3000, "2026-01-01")
    return eid


@pytest.fixture()
def reglas_antiguas(conn, admin, monkeypatch):
    """Estas pruebas cubren el motor de cálculo con las reglas genéricas (extra automática, doble, justificadas pagadas)."""
    for clave, valor in (("horas_extra_automaticas", "si"), ("nomina_pago_hora_extra", "0"),
                         ("asistencia_paga_justificada", "si")):
        configuracion.establecer(conn, admin, clave, valor)
    monkeypatch.setattr(nomina, "hoy", lambda: date(2026, 11, 16))


def test_calendario_de_referencia():
    assert date(2026, 11, 2).isoweekday() == 1  # el 2 de noviembre de 2026 es lunes


# ---------- asistencia ---------------------------------------------------------

def test_entrada_con_tolerancia_y_retardo(conn, admin, empleado, ana):
    r = empleados.registrar_entrada(conn, empleado, ana, dt(2, 9, 8))  # 8 min: dentro de tolerancia
    assert r["estado"] == "presente" and r["minutos_retardo"] == 0
    r = empleados.registrar_entrada(conn, empleado, ana, dt(3, 9, 25))
    assert r["estado"] == "retardo" and r["minutos_retardo"] == 25
    with pytest.raises(ErrorNegocio):  # una sola asistencia por día
        empleados.registrar_entrada(conn, empleado, ana, dt(3, 9, 40))


def test_salida_calcula_horas_extra(conn, empleado, ana, reglas_antiguas):
    empleados.registrar_entrada(conn, empleado, ana, dt(2, 9, 0))
    r = empleados.registrar_salida(conn, empleado, ana, dt(2, 18, 30))
    assert r["horas_trabajadas"] == D("9.50") and r["horas_extra"] == D("1.50")
    with pytest.raises(ErrorNegocio):  # ya no hay entrada abierta
        empleados.registrar_salida(conn, empleado, ana, dt(2, 19, 0))


def test_domingo_sin_turno_no_genera_retardo_ni_extra(conn, empleado, ana):
    empleados.registrar_entrada(conn, empleado, ana, dt(1, 15, 0))  # domingo
    r = empleados.registrar_salida(conn, empleado, ana, dt(1, 23, 0))
    assert r["horas_extra"] == D("0.00")


def test_solo_admin_marca_faltas_y_corrige(conn, admin, empleado, ana):
    with pytest.raises(ErrorAcceso):
        empleados.marcar_estado(conn, empleado, ana, "2026-11-04", "falta")
    with pytest.raises(ErrorNegocio):  # justificada exige explicación
        empleados.marcar_estado(conn, admin, ana, "2026-11-04", "justificada")
    empleados.marcar_estado(conn, admin, ana, "2026-11-04", "falta")
    empleados.registrar_entrada(conn, empleado, ana, dt(5, 9, 0))
    with pytest.raises(ErrorNegocio):  # ya tiene entrada: debe corregirse con motivo
        empleados.marcar_estado(conn, admin, ana, "2026-11-05", "falta")
    r = empleados.corregir_asistencia(conn, admin, ana, "2026-11-05", dt(5, 9, 40), dt(5, 17, 0), "Olvidó checar")
    assert r["estado"] == "retardo" and r["minutos_retardo"] == 40


def test_turnos_nuevos_conservan_historial(conn, admin, ana):
    empleados.definir_turnos(conn, admin, ana, [(1, "10:00", "18:00")], "2026-12-01")
    assert len(empleados.turnos_vigentes(conn, ana, "2026-11-15")) == 6  # horario anterior
    nuevos = empleados.turnos_vigentes(conn, ana, "2026-12-10")
    assert len(nuevos) == 1 and str(nuevos[0]["hora_entrada"]) == "10:00:00"
    with pytest.raises(ErrorNegocio):
        empleados.definir_turnos(conn, admin, ana, [(1, "10:00", "18:00"), (1, "11:00", "19:00")], "2027-01-01")


def test_baja_desactiva_usuario_pero_no_al_ultimo_admin(conn, admin):
    from oceanica.servicios import usuarios
    eid = empleados.crear_empleado(conn, admin, "Beto", "Ruiz", "2026-02-01")
    uid = usuarios.crear_usuario(conn, admin, "beto", "Clave#Larga1", "empleado", empleado_id=eid)
    empleados.dar_de_baja(conn, admin, eid, "2026-10-31")
    assert [u for u in usuarios.listar_usuarios(conn, admin) if u["id"] == uid][0]["activo"] == 0
    with pytest.raises(ErrorNegocio):
        empleados.dar_de_baja(conn, admin, eid, "2026-10-31")
    eadmin = empleados.crear_empleado(conn, admin, "Dueño", "Uno", "2026-01-01")
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET empleado_id = %s WHERE id = %s", (eadmin, admin["id"]))
    conn.commit()
    with pytest.raises(ErrorNegocio):
        empleados.dar_de_baja(conn, admin, eadmin, "2026-10-31")


# ---------- salarios y periodos --------------------------------------------------

def test_empleado_no_ve_nomina_ni_salarios(conn, empleado, ana):
    with pytest.raises(ErrorAcceso):
        nomina.listar_periodos(conn, empleado)
    with pytest.raises(ErrorAcceso):
        nomina.historial_salarios(conn, empleado, ana)
    with pytest.raises(ErrorAcceso):
        nomina.fijar_salario(conn, empleado, ana, "dia", 100, "2026-02-01")


def test_cambio_de_salario_mantiene_historial(conn, admin, ana):
    nomina.fijar_salario(conn, admin, ana, "quincena", 3300, "2026-07-01")
    h = nomina.historial_salarios(conn, admin, ana)
    assert [x["monto"] for x in h] == [D("3300.00"), D("3000.00")]
    assert h[1]["vigente_hasta"] == date(2026, 6, 30) and h[0]["vigente_hasta"] is None
    with pytest.raises(ErrorNegocio):
        nomina.fijar_salario(conn, admin, ana, "quincena", 3500, "2026-06-01")  # anterior al vigente


def test_periodos_validos_y_sin_traslape(conn, admin):
    nomina.abrir_periodo(conn, admin, "quincenal", "2026-11-01", "2026-11-15")
    with pytest.raises(ErrorNegocio):
        nomina.abrir_periodo(conn, admin, "quincenal", "2026-11-10", "2026-11-24")
    with pytest.raises(ErrorNegocio):
        nomina.abrir_periodo(conn, admin, "semanal", "2026-12-01", "2026-12-09")  # 9 días
    nomina.abrir_periodo(conn, admin, "quincenal", "2026-11-16", "2026-11-30")


def _capturar_asistencia_de_ana(conn, admin, empleado, ana):
    empleados.corregir_asistencia(conn, admin, ana, "2026-11-02", dt(2, 9, 0), dt(2, 19, 0), "Captura")  # 2 h extra
    empleados.corregir_asistencia(conn, admin, ana, "2026-11-03", dt(3, 9, 30), dt(3, 17, 0), "Captura")  # retardo
    empleados.marcar_estado(conn, admin, ana, "2026-11-04", "falta")
    empleados.marcar_estado(conn, admin, ana, "2026-11-05", "justificada", "Cita médica")


def test_nomina_quincenal_con_extras_faltas_y_conceptos_manuales(conn, admin, ana, reglas_antiguas):
    _capturar_asistencia_de_ana(conn, admin, None, ana)
    pid = nomina.abrir_periodo(conn, admin, "quincenal", "2026-11-01", "2026-11-15")
    r = nomina.calcular_periodo(conn, admin, pid)
    assert r["empleados"] == 1
    assert any("sin registro en días de trabajo" in a for a in r["advertencias"])
    n = nomina.obtener_periodo(conn, admin, pid)["nominas"][0]
    # base 3000 + extras (2 h x (200/8) x 2 = 100) - 1 falta (200) = 2900
    assert (n["total_percepciones"], n["total_deducciones"], n["neto"]) == (D("3100.00"), D("200.00"), D("2900.00"))
    assert n["dias_trabajados"] == D("3.00")  # presente, retardo y justificada

    nomina.agregar_concepto(conn, admin, n["id"], "BONO", 500, "Productividad")
    t = nomina.agregar_concepto(conn, admin, n["id"], "DESCMAN", 150, "Uniforme")
    assert t["neto"] == D("3250.00")
    with pytest.raises(ErrorNegocio):  # los automáticos no se capturan a mano
        nomina.agregar_concepto(conn, admin, n["id"], "SUELDO", 100, "x")
    with pytest.raises(ErrorNegocio):  # descuento que deja el neto negativo
        nomina.agregar_concepto(conn, admin, n["id"], "DESCMAN", 99999, "x")

    nomina.calcular_periodo(conn, admin, pid)  # recalcular conserva lo manual
    n = nomina.obtener_periodo(conn, admin, pid)["nominas"][0]
    assert n["neto"] == D("3250.00") and sum(1 for d in n["detalle"] if not d["automatico"]) == 2


def test_justificada_no_pagada_segun_configuracion(conn, admin, ana, reglas_antiguas):
    eid = empleados.crear_empleado(conn, admin, "Dora", "Vega", "2026-01-01")
    nomina.fijar_salario(conn, admin, eid, "dia", 300, "2026-01-01")
    for d in (2, 3):
        empleados.corregir_asistencia(conn, admin, eid, f"2026-11-0{d}", dt(d, 9, 0), dt(d, 17, 0), "Captura")
    empleados.marcar_estado(conn, admin, eid, "2026-11-04", "justificada", "Cita")
    pid = nomina.abrir_periodo(conn, admin, "quincenal", "2026-11-01", "2026-11-15")
    nomina.calcular_periodo(conn, admin, pid)
    por_nombre = {n["empleado"]: n for n in nomina.obtener_periodo(conn, admin, pid)["nominas"]}
    assert por_nombre["Dora Vega"]["neto"] == D("900.00")  # 3 días pagados
    configuracion.establecer(conn, admin, "asistencia_paga_justificada", "no")
    nomina.calcular_periodo(conn, admin, pid)
    por_nombre = {n["empleado"]: n for n in nomina.obtener_periodo(conn, admin, pid)["nominas"]}
    assert por_nombre["Dora Vega"]["neto"] == D("600.00")


def test_pago_por_hora(conn, admin):
    eid = empleados.crear_empleado(conn, admin, "Hugo", "Paz", "2026-01-01")
    nomina.fijar_salario(conn, admin, eid, "hora", 40, "2026-01-01")
    empleados.corregir_asistencia(conn, admin, eid, "2026-11-02", dt(2, 9, 0), dt(2, 17, 0), "Captura")  # 8 h
    empleados.corregir_asistencia(conn, admin, eid, "2026-11-03", dt(3, 10, 0), dt(3, 15, 0), "Captura")  # 5 h
    pid = nomina.abrir_periodo(conn, admin, "semanal", "2026-11-02", "2026-11-08")
    nomina.calcular_periodo(conn, admin, pid)
    n = nomina.obtener_periodo(conn, admin, pid)["nominas"][0]
    assert n["horas_trabajadas"] == D("13.00") and n["neto"] == D("520.00")


def test_proporcional_por_ingreso_a_mitad_de_periodo(conn, admin):
    eid = empleados.crear_empleado(conn, admin, "Iris", "Mora", "2026-11-09")  # activa 7 de 15 días
    nomina.fijar_salario(conn, admin, eid, "quincena", 3000, "2026-11-09")
    pid = nomina.abrir_periodo(conn, admin, "quincenal", "2026-11-01", "2026-11-15")
    nomina.calcular_periodo(conn, admin, pid)
    assert nomina.obtener_periodo(conn, admin, pid)["nominas"][0]["neto"] == D("1400.00")  # 3000 x 7/15


def test_esquema_semanal_en_periodo_quincenal_se_prorratea(conn, admin):
    eid = empleados.crear_empleado(conn, admin, "Juan", "Soto", "2026-01-01")
    nomina.fijar_salario(conn, admin, eid, "semana", 700, "2026-01-01")
    pid = nomina.abrir_periodo(conn, admin, "quincenal", "2026-11-01", "2026-11-15")
    nomina.calcular_periodo(conn, admin, pid)
    assert nomina.obtener_periodo(conn, admin, pid)["nominas"][0]["neto"] == D("1500.00")  # 700 x 15/7


def test_empleado_sin_sueldo_genera_advertencia(conn, admin):
    empleados.crear_empleado(conn, admin, "Kari", "Luna", "2026-01-01")
    pid = nomina.abrir_periodo(conn, admin, "quincenal", "2026-11-01", "2026-11-15")
    r = nomina.calcular_periodo(conn, admin, pid)
    assert r["empleados"] == 0
    assert len(r["advertencias"]) == 1 and "no tiene sueldo" in r["advertencias"][0]
    with pytest.raises(ErrorNegocio):  # nada que aprobar
        nomina.aprobar_periodo(conn, admin, pid)


def test_ciclo_completo_aprobar_pagar_en_caja_y_cerrar(conn, admin, ana, reglas_antiguas):
    _capturar_asistencia_de_ana(conn, admin, None, ana)
    pid = nomina.abrir_periodo(conn, admin, "quincenal", "2026-11-01", "2026-11-15")
    nomina.calcular_periodo(conn, admin, pid)
    nid = nomina.obtener_periodo(conn, admin, pid)["nominas"][0]["id"]
    with pytest.raises(ErrorNegocio):  # aún no está aprobada
        nomina.registrar_pago_empleado(conn, admin, nid)
    nomina.aprobar_periodo(conn, admin, pid)
    with pytest.raises(ErrorNegocio):  # aprobada: ya no se recalcula ni se editan conceptos
        nomina.calcular_periodo(conn, admin, pid)
    with pytest.raises(ErrorNegocio):
        nomina.agregar_concepto(conn, admin, nid, "BONO", 10, "x")
    with pytest.raises(ErrorNegocio):  # pago en caja sin caja abierta
        nomina.registrar_pago_empleado(conn, admin, nid, en_caja=True)
    caja.abrir_corte(conn, admin, 5000)
    nomina.registrar_pago_empleado(conn, admin, nid, en_caja=True)
    assert caja.resumen_corte(conn)["gastos"] == D("2900.00")
    with pytest.raises(ErrorNegocio):  # no se paga dos veces
        nomina.registrar_pago_empleado(conn, admin, nid)
    with pytest.raises(ErrorNegocio):  # con pagos ya no se reabre
        nomina.reabrir_periodo(conn, admin, pid)
    nomina.cerrar_periodo(conn, admin, pid)
    assert nomina.obtener_periodo(conn, admin, pid)["estado"] == "cerrado"
    recibo = nomina.datos_recibo(conn, admin, nid)
    assert recibo["nomina"]["empleado"] == "Ana Torres" and recibo["nomina"]["neto"] == D("2900.00")


def test_no_se_cierra_con_nominas_sin_pagar(conn, admin, ana):
    pid = nomina.abrir_periodo(conn, admin, "quincenal", "2026-11-01", "2026-11-15")
    nomina.calcular_periodo(conn, admin, pid)
    nomina.aprobar_periodo(conn, admin, pid)
    with pytest.raises(ErrorNegocio):
        nomina.cerrar_periodo(conn, admin, pid)
    nomina.reabrir_periodo(conn, admin, pid)  # sin pagos sí se puede reabrir
    assert nomina.obtener_periodo(conn, admin, pid)["estado"] == "abierto"
