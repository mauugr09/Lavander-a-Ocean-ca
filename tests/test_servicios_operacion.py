"""Integración: clientes, catálogo, órdenes, caja e inventario contra una base real."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from oceanica.seguridad import ErrorAcceso
from oceanica.servicios import caja, catalogo, clientes, configuracion, inventario, ordenes, usuarios
from oceanica.servicios.comunes import ErrorNegocio

D = Decimal


@pytest.fixture()
def servicio_kilo(conn, admin):
    cat = catalogo.listar_categorias(conn)[0]["id"]
    return catalogo.crear_servicio(conn, admin, cat, "Lavado y secado", "kilo", "28.50")


@pytest.fixture()
def servicio_pieza(conn, admin):
    cat = catalogo.listar_categorias(conn)[0]["id"]
    return catalogo.crear_servicio(conn, admin, cat, "Edredón matrimonial", "pieza", "120")


def _efectivo(conn):
    cur = conn.cursor()
    cur.execute("SELECT id FROM metodos_pago WHERE es_efectivo = 1")
    return cur.fetchone()[0]


# ---------- catálogo y clientes ------------------------------------------------

def test_empleado_no_puede_crear_servicios(conn, empleado):
    with pytest.raises(ErrorAcceso):
        catalogo.crear_servicio(conn, empleado, 1, "X", "kilo", 10)


def test_servicio_duplicado_y_precio_negativo(conn, admin, servicio_kilo):
    cat = catalogo.listar_categorias(conn)[0]["id"]
    with pytest.raises(ErrorNegocio):
        catalogo.crear_servicio(conn, admin, cat, "Lavado y secado", "kilo", 30)
    with pytest.raises(ErrorNegocio):
        catalogo.crear_servicio(conn, admin, cat, "Otro", "kilo", -1)


def test_busqueda_de_clientes_por_nombre_y_telefono(conn, empleado):
    clientes.crear_cliente(conn, empleado, "María", "López", "5512345678")
    clientes.crear_cliente(conn, empleado, "Juan", "Pérez", "5587654321")
    assert [c["nombre"] for c in clientes.buscar_clientes(conn, "lopez")] == ["María"]  # ignora acentos
    assert [c["nombre"] for c in clientes.buscar_clientes(conn, "López")] == ["María"]
    assert [c["nombre"] for c in clientes.buscar_clientes(conn, "MARIA lopez")] == ["María"]
    assert [c["nombre"] for c in clientes.buscar_clientes(conn, "8765")] == ["Juan"]
    assert len(clientes.buscar_clientes(conn, "%")) == 0  # el comodín no se interpreta


# ---------- órdenes ------------------------------------------------------------

def test_crear_orden_calcula_totales_y_folio(conn, empleado, servicio_kilo, servicio_pieza):
    cid = clientes.crear_cliente(conn, empleado, "Ana")
    oid = ordenes.crear_orden(conn, empleado, [
        {"servicio_id": servicio_kilo, "cantidad": "3.5"},
        {"servicio_id": servicio_pieza, "cantidad": 2},
    ], cliente_id=cid)
    o = ordenes.obtener_orden(conn, oid)
    assert o["folio"] == "OC-000001"
    assert o["subtotal"] == D("339.75") and o["total"] == D("339.75")  # 3.5*28.50 + 2*120
    assert o["saldo"] == D("339.75") and o["estado"] == "recibida"
    assert len(o["detalle"]) == 2 and len(o["historial"]) == 1
    oid2 = ordenes.crear_orden(conn, empleado, [{"servicio_id": servicio_kilo, "cantidad": 1}])
    assert ordenes.obtener_orden(conn, oid2)["folio"] == "OC-000002"


def test_piezas_deben_ser_enteras(conn, empleado, servicio_pieza):
    with pytest.raises(ErrorNegocio):
        ordenes.crear_orden(conn, empleado, [{"servicio_id": servicio_pieza, "cantidad": "1.5"}])


def test_precio_historico_no_cambia_al_actualizar_servicio(conn, admin, empleado, servicio_kilo):
    oid = ordenes.crear_orden(conn, empleado, [{"servicio_id": servicio_kilo, "cantidad": 2}])
    catalogo.actualizar_servicio(conn, admin, servicio_kilo, precio=99)
    assert ordenes.obtener_orden(conn, oid)["total"] == D("57.00")


def test_empleado_no_da_descuentos_por_defecto(conn, empleado, servicio_kilo):
    items = [{"servicio_id": servicio_kilo, "cantidad": 10}]
    with pytest.raises(ErrorNegocio, match="0%"):
        ordenes.crear_orden(conn, empleado, items, descuento=1)


def test_descuento_de_empleado_tiene_tope(conn, admin, empleado, servicio_kilo):
    configuracion.establecer(conn, admin, "descuento_max_pct_empleado", "10")
    items = [{"servicio_id": servicio_kilo, "cantidad": 10}]  # 285.00
    with pytest.raises(ErrorNegocio):
        ordenes.crear_orden(conn, empleado, items, descuento=60)  # >10%
    ordenes.crear_orden(conn, empleado, items, descuento="28.50")  # exactamente 10%
    oid = ordenes.crear_orden(conn, admin, items, descuento=100)
    assert ordenes.obtener_orden(conn, oid)["total"] == D("185.00")


def test_orden_sin_servicios_o_con_servicio_inexistente(conn, empleado):
    with pytest.raises(ErrorNegocio):
        ordenes.crear_orden(conn, empleado, [])
    with pytest.raises(ErrorNegocio):
        ordenes.crear_orden(conn, empleado, [{"servicio_id": 999, "cantidad": 1}])


def test_anticipo_requiere_caja_y_es_atomico(conn, empleado, servicio_kilo):
    items = [{"servicio_id": servicio_kilo, "cantidad": 2}]
    anticipo = {"metodo_pago_id": _efectivo(conn), "monto": 20}
    with pytest.raises(ErrorNegocio):
        ordenes.crear_orden(conn, empleado, items, anticipo=anticipo)
    assert ordenes.listar_ordenes(conn) == []  # no quedó una orden a medias
    caja.abrir_corte(conn, empleado, 100)
    oid = ordenes.crear_orden(conn, empleado, items, anticipo=anticipo)
    o = ordenes.obtener_orden(conn, oid)
    assert o["pagado"] == D("20.00") and o["saldo"] == D("37.00")
    with pytest.raises(ErrorNegocio):  # anticipo mayor al total
        ordenes.crear_orden(conn, empleado, items, anticipo={**anticipo, "monto": 500})


def test_flujo_de_estados_y_entrega_con_saldo(conn, admin, empleado, servicio_kilo):
    caja.abrir_corte(conn, empleado, 0)
    oid = ordenes.crear_orden(conn, empleado, [{"servicio_id": servicio_kilo, "cantidad": 2}])
    ordenes.cambiar_estado(conn, empleado, oid, "en_proceso")
    ordenes.cambiar_estado(conn, empleado, oid, "lista")
    with pytest.raises(ErrorNegocio):  # saldo pendiente
        ordenes.cambiar_estado(conn, empleado, oid, "entregada")
    with pytest.raises(ErrorNegocio):  # un empleado no puede regresar de estado
        ordenes.cambiar_estado(conn, empleado, oid, "en_proceso", "x")
    with pytest.raises(ErrorNegocio):  # el empleado no puede forzar la entrega
        ordenes.cambiar_estado(conn, empleado, oid, "entregada", "x", forzar_entrega=True)
    caja.registrar_pago(conn, empleado, oid, _efectivo(conn), 57)
    ordenes.cambiar_estado(conn, empleado, oid, "entregada")
    o = ordenes.obtener_orden(conn, oid)
    assert o["estado"] == "entregada" and o["fecha_entrega"] is not None
    assert [h["estado_nuevo"] for h in o["historial"]] == ["recibida", "en_proceso", "lista", "entregada"]
    with pytest.raises(ErrorNegocio):  # estado terminal
        ordenes.cambiar_estado(conn, admin, oid, "lista", "x")


def test_admin_puede_entregar_con_saldo_con_motivo(conn, admin, servicio_kilo):
    oid = ordenes.crear_orden(conn, admin, [{"servicio_id": servicio_kilo, "cantidad": 1}])
    with pytest.raises(ErrorNegocio):
        ordenes.cambiar_estado(conn, admin, oid, "entregada", forzar_entrega=True)  # sin motivo
    ordenes.cambiar_estado(conn, admin, oid, "entregada", "Cliente frecuente, paga mañana", forzar_entrega=True)


def test_cancelar_exige_reembolso_previo(conn, admin, empleado, servicio_kilo):
    caja.abrir_corte(conn, empleado, 0)
    oid = ordenes.crear_orden(conn, empleado, [{"servicio_id": servicio_kilo, "cantidad": 2}],
                              anticipo={"metodo_pago_id": _efectivo(conn), "monto": 10})
    with pytest.raises(ErrorNegocio):
        ordenes.cancelar_orden(conn, empleado, oid, "Cliente se arrepintió")
    with pytest.raises(ErrorNegocio):  # empleado no reembolsa
        caja.registrar_pago(conn, empleado, oid, _efectivo(conn), 10, tipo="reembolso")
    caja.registrar_pago(conn, admin, oid, _efectivo(conn), 10, tipo="reembolso")
    ordenes.cancelar_orden(conn, empleado, oid, "Cliente se arrepintió")
    assert ordenes.obtener_orden(conn, oid)["estado"] == "cancelada"
    with pytest.raises(ErrorNegocio):  # no se cobra una orden cancelada
        caja.registrar_pago(conn, empleado, oid, _efectivo(conn), 5)


def test_listar_ordenes_filtra(conn, empleado, servicio_kilo):
    cid = clientes.crear_cliente(conn, empleado, "Lucía", "Gómez", "5500001111")
    a = ordenes.crear_orden(conn, empleado, [{"servicio_id": servicio_kilo, "cantidad": 1}], cliente_id=cid)
    ordenes.crear_orden(conn, empleado, [{"servicio_id": servicio_kilo, "cantidad": 1}])
    ordenes.cambiar_estado(conn, empleado, a, "lista")
    assert len(ordenes.listar_ordenes(conn, solo_abiertas=True)) == 2
    assert [o["folio"] for o in ordenes.listar_ordenes(conn, estados=["lista"])] == ["OC-000001"]
    assert len(ordenes.listar_ordenes(conn, texto_busqueda="Gómez")) == 1
    assert len(ordenes.listar_ordenes(conn, texto_busqueda="OC-000002")) == 1


# ---------- caja ---------------------------------------------------------------

def test_pagos_no_pueden_exceder_el_saldo(conn, empleado, servicio_kilo):
    caja.abrir_corte(conn, empleado, 0)
    oid = ordenes.crear_orden(conn, empleado, [{"servicio_id": servicio_kilo, "cantidad": 2}])  # 57.00
    caja.registrar_pago(conn, empleado, oid, _efectivo(conn), 50)
    with pytest.raises(ErrorNegocio):
        caja.registrar_pago(conn, empleado, oid, _efectivo(conn), 8)
    caja.registrar_pago(conn, empleado, oid, _efectivo(conn), 7)
    with pytest.raises(ErrorNegocio):
        caja.registrar_pago(conn, empleado, oid, _efectivo(conn), 1)


def test_corte_de_caja_completo(conn, admin, empleado, servicio_kilo):
    metodos = {m["nombre"]: m["id"] for m in _metodos(conn)}
    caja.abrir_corte(conn, empleado, 200)
    with pytest.raises(ErrorNegocio):  # solo una caja abierta a la vez
        caja.abrir_corte(conn, admin, 0)
    o1 = ordenes.crear_orden(conn, empleado, [{"servicio_id": servicio_kilo, "cantidad": 4}])  # 114
    o2 = ordenes.crear_orden(conn, empleado, [{"servicio_id": servicio_kilo, "cantidad": 2}])  # 57
    caja.registrar_pago(conn, empleado, o1, metodos["Efectivo"], 114)
    caja.registrar_pago(conn, empleado, o2, metodos["Tarjeta"], 57)
    caja.registrar_movimiento(conn, empleado, "gasto", "Bolsas", 30)
    with pytest.raises(ErrorAcceso):  # retiros solo administrador
        caja.registrar_movimiento(conn, empleado, "retiro", "Para el banco", 50)
    caja.registrar_movimiento(conn, admin, "retiro", "Para el banco", 100)
    r = caja.resumen_corte(conn)
    assert r["total_cobrado"] == D("171.00") and r["efectivo_cobrado"] == D("114.00")
    assert r["efectivo_esperado"] == D("184.00")  # 200 + 114 - 30 - 100
    with pytest.raises(ErrorNegocio):  # diferencia sin observación
        caja.cerrar_corte(conn, empleado, 180)
    cerrado = caja.cerrar_corte(conn, empleado, 180, "Faltaron 4 pesos de cambio")
    assert cerrado["diferencia"] == D("-4.00")
    assert caja.corte_abierto(conn) is None
    with pytest.raises(ErrorNegocio):  # sin caja abierta no se cobra
        caja.registrar_pago(conn, empleado, o1, metodos["Efectivo"], 1)


def test_corte_cuadrado_cierra_sin_observaciones(conn, empleado):
    caja.abrir_corte(conn, empleado, 150)
    assert caja.cerrar_corte(conn, empleado, 150)["diferencia"] == D("0.00")


def _metodos(conn):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, nombre FROM metodos_pago")
    return cur.fetchall()


# ---------- inventario ---------------------------------------------------------

@pytest.fixture()
def detergente(conn, admin):
    cat = inventario.listar_categorias(conn)[0]["id"]
    return inventario.crear_insumo(conn, admin, cat, "Detergente líquido", "litro", minimo=5,
                                   costo_unitario=40, existencia_inicial=20)


def test_entradas_y_salidas_actualizan_existencia(conn, empleado, detergente):
    i = inventario.registrar_movimiento(conn, empleado, detergente, "salida", 8, "Lavado del día")
    assert i["existencia"] == D("12.00") and not i["bajo"]
    i = inventario.registrar_movimiento(conn, empleado, detergente, "salida", 7, "Lavado del día")
    assert i["bajo"]  # 5 <= mínimo 5
    assert [x["nombre"] for x in inventario.listar_insumos(conn, solo_bajos=True)] == ["Detergente líquido"]
    i = inventario.registrar_movimiento(conn, empleado, detergente, "entrada", 10, "Compra", costo_unitario=42)
    assert i["existencia"] == D("15.00") and i["costo_unitario"] == D("42.00")
    movs = inventario.movimientos_insumo(conn, detergente)
    assert movs[0]["existencia_resultante"] == D("15.00") and len(movs) == 4


def test_no_se_permite_existencia_negativa(conn, empleado, detergente):
    with pytest.raises(ErrorNegocio):
        inventario.registrar_movimiento(conn, empleado, detergente, "salida", 21, "Consumo")
    assert inventario.listar_insumos(conn)[0]["existencia"] == D("20.00")


def test_ajuste_solo_admin_y_deja_rastro(conn, admin, empleado, detergente):
    with pytest.raises(ErrorAcceso):
        inventario.ajustar_existencia(conn, empleado, detergente, 3, "Conteo")
    i = inventario.ajustar_existencia(conn, admin, detergente, 17.5, "Conteo físico")
    assert i["existencia"] == D("17.50")
    m = inventario.movimientos_insumo(conn, detergente)[0]
    assert m["tipo"] == "ajuste" and m["cantidad"] == D("2.50") and "20.00 -> 17.50" in m["motivo"]
    ajuste_a_cero = inventario.ajustar_existencia(conn, admin, detergente, 0, "Se terminó")
    assert ajuste_a_cero["existencia"] == D("0.00")


# ---------- usuarios -----------------------------------------------------------

def test_no_se_puede_desactivar_al_ultimo_admin(conn, admin):
    with pytest.raises(ErrorNegocio):
        usuarios.cambiar_estado(conn, admin, admin["id"], False)
    otro = usuarios.crear_usuario(conn, admin, "otro_admin", "Clave#Larga1", "administrador")
    usuarios.cambiar_estado(conn, admin, otro, False)  # ya hay otro activo (él mismo): permitido sobre 'otro'
    with pytest.raises(ErrorNegocio):
        usuarios.cambiar_estado(conn, admin, admin["id"], False)  # no a sí mismo


def test_cambio_de_password(conn, admin):
    uid = usuarios.crear_usuario(conn, admin, "nuevo", "Temporal#123", "empleado")
    sesion = {"id": uid, "usuario": "nuevo", "rol": "empleado"}
    with pytest.raises(ErrorAcceso):
        usuarios.cambiar_password(conn, sesion, "incorrecta", "Definitiva#456")
    with pytest.raises(ErrorNegocio):
        usuarios.cambiar_password(conn, sesion, "Temporal#123", "corta")
    usuarios.cambiar_password(conn, sesion, "Temporal#123", "Definitiva#456")
    from oceanica.seguridad import iniciar_sesion
    assert iniciar_sesion(conn, "nuevo", "Definitiva#456")["debe_cambiar_password"] is False
