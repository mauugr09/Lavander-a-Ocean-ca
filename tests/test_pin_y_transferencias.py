"""Integración: PIN de mostrador y transferencias por confirmar."""
import pytest

from oceanica import seguridad
from oceanica.seguridad import ErrorAcceso, autenticar_pin, validar_pin
from oceanica.servicios import caja, catalogo, configuracion, empleados, ordenes, reportes, tickets, usuarios
from oceanica.servicios.comunes import ErrorNegocio


def _id(conn, tabla, nombre):
    cur = conn.cursor()
    cur.execute(f"SELECT id FROM {tabla} WHERE nombre = %s", (nombre,))
    return cur.fetchone()[0]


# ---------- PIN ---------------------------------------------------------------

@pytest.mark.parametrize("pin", ["123", "1234567", "abcd", "1111", "1234", "4321", "９９９９", "12 4"])
def test_pin_invalido(pin):
    assert validar_pin(pin)


@pytest.mark.parametrize("pin", ["2580", "135790", "4827"])
def test_pin_valido(pin):
    assert validar_pin(pin) == []


def test_asignar_y_usar_pin(conn, admin, empleado):
    usuarios.asignar_pin(conn, admin, empleado["id"], "482615")
    s = autenticar_pin(conn, empleado["id"], "482615")
    assert s["id"] == empleado["id"] and s["rol"] == "empleado"
    with pytest.raises(ErrorAcceso):
        autenticar_pin(conn, empleado["id"], "000999")


def test_pin_solo_admin_asigna_y_no_para_administradores(conn, admin, empleado):
    with pytest.raises(ErrorAcceso):
        usuarios.asignar_pin(conn, empleado, empleado["id"], "482615")
    with pytest.raises(ErrorNegocio):
        usuarios.asignar_pin(conn, admin, admin["id"], "482615")
    with pytest.raises(ErrorAcceso):  # sin PIN asignado
        autenticar_pin(conn, empleado["id"], "482615")


def test_pin_bloqueo_tras_cinco_fallos(conn, admin, empleado):
    usuarios.asignar_pin(conn, admin, empleado["id"], "482615")
    for _ in range(seguridad.MAX_INTENTOS):
        with pytest.raises(ErrorAcceso):
            autenticar_pin(conn, empleado["id"], "999000")
    with pytest.raises(ErrorAcceso, match="bloqueada"):
        autenticar_pin(conn, empleado["id"], "482615")
    usuarios.asignar_pin(conn, admin, empleado["id"], "482615")  # el administrador desbloquea
    assert autenticar_pin(conn, empleado["id"], "482615")["id"] == empleado["id"]


def test_cambiar_pin_propio(conn, admin, empleado):
    usuarios.asignar_pin(conn, admin, empleado["id"], "482615")
    with pytest.raises(ErrorAcceso):
        usuarios.cambiar_pin(conn, empleado, "000999", "703518")
    usuarios.cambiar_pin(conn, empleado, "482615", "703518")
    assert autenticar_pin(conn, empleado["id"], "703518")


def test_listar_para_pin_marca_presentes(conn, admin):
    eid = empleados.crear_empleado(conn, admin, "Luis", "Mora", "2026-01-01")
    uid = usuarios.crear_usuario(conn, admin, "luis", "Temporal#123", "empleado", eid)
    assert usuarios.listar_para_pin(conn) == []  # sin PIN no aparece
    usuarios.asignar_pin(conn, admin, uid, "482615")
    f = usuarios.listar_para_pin(conn)
    assert len(f) == 1 and f[0]["nombre"] == "Luis Mora" and f[0]["presente"] is False
    s = autenticar_pin(conn, uid, "482615")
    empleados.registrar_entrada(conn, s, s["empleado_id"])
    assert usuarios.listar_para_pin(conn)[0]["presente"] is True


# ---------- Transferencias -----------------------------------------------------

@pytest.fixture()
def orden(conn, admin, empleado):
    cat = catalogo.listar_categorias(conn)[0]["id"]
    sid = catalogo.crear_servicio(conn, admin, cat, "Lavado", "kilo", 20)
    caja.abrir_corte(conn, empleado, 0)
    oid = ordenes.crear_orden(conn, empleado, [{"servicio_id": sid, "cantidad": 10}])  # 200
    ordenes.cambiar_estado(conn, empleado, oid, "en_proceso")
    ordenes.cambiar_estado(conn, empleado, oid, "lista")
    return oid


def test_transferencia_exige_referencia_y_queda_pendiente(conn, empleado, orden):
    tr = _id(conn, "metodos_pago", "Transferencia")
    with pytest.raises(ErrorNegocio, match="clave de rastreo"):
        caja.registrar_pago(conn, empleado, orden, tr, 200)
    caja.registrar_pago(conn, empleado, orden, tr, 200, referencia="MBAN123")
    o = ordenes.obtener_orden(conn, orden)
    assert o["saldo"] == 0 and o["por_confirmar"] == 200
    assert o["pagos"][0]["estado_confirmacion"] == "pendiente"
    assert "POR CONFIRMAR" in tickets.ticket_orden_texto(conn, orden)
    assert caja.resumen_corte(conn)["transferencias_pendientes"] == {"cantidad": 1, "total": 200}


def test_entrega_con_transferencia_pendiente_segun_configuracion(conn, admin, empleado, orden):
    tr = _id(conn, "metodos_pago", "Transferencia")
    caja.registrar_pago(conn, empleado, orden, tr, 200, referencia="MBAN123")
    configuracion.establecer(conn, admin, "entrega_transferencia_pendiente", "no")
    with pytest.raises(ErrorNegocio, match="por confirmar"):
        ordenes.cambiar_estado(conn, admin, orden, "entregada")
    configuracion.establecer(conn, admin, "entrega_transferencia_pendiente", "admin")
    with pytest.raises(ErrorNegocio, match="administrador"):
        ordenes.cambiar_estado(conn, empleado, orden, "entregada")
    configuracion.establecer(conn, admin, "entrega_transferencia_pendiente", "todos")
    ordenes.cambiar_estado(conn, empleado, orden, "entregada")
    assert ordenes.obtener_orden(conn, orden)["estado"] == "entregada"
    with pytest.raises(ErrorNegocio):
        configuracion.establecer(conn, admin, "entrega_transferencia_pendiente", "quizas")


def test_confirmar_transferencia(conn, admin, empleado, orden):
    tr = _id(conn, "metodos_pago", "Transferencia")
    pid = caja.registrar_pago(conn, empleado, orden, tr, 200, referencia="MBAN123")
    with pytest.raises(ErrorAcceso):
        caja.confirmar_transferencia(conn, empleado, pid)
    assert [f["folio"] for f in reportes.transferencias_pendientes(conn, admin)["filas"]] == ["OC-000001"]
    caja.confirmar_transferencia(conn, admin, pid)
    assert ordenes.obtener_orden(conn, orden)["por_confirmar"] == 0
    assert reportes.transferencias_pendientes(conn, admin)["filas"] == []
    with pytest.raises(ErrorNegocio, match="ya está confirmado"):
        caja.confirmar_transferencia(conn, admin, pid)
    ordenes.cambiar_estado(conn, empleado, orden, "entregada")  # con 'no' también se podría ahora


def test_rechazar_transferencia_devuelve_saldo(conn, admin, empleado, orden):
    tr = _id(conn, "metodos_pago", "Transferencia")
    pid = caja.registrar_pago(conn, empleado, orden, tr, 200, referencia="MBAN123")
    with pytest.raises(ErrorNegocio, match="reembolsar"):
        caja.registrar_pago(conn, admin, orden, tr, 200, tipo="reembolso")
    caja.rechazar_transferencia(conn, admin, pid, "No llegó al banco")
    o = ordenes.obtener_orden(conn, orden)
    assert o["saldo"] == 200 and o["por_confirmar"] == 0
    assert [p["estado_confirmacion"] for p in o["pagos"]] == ["rechazado", "rechazado"]
    with pytest.raises(ErrorNegocio, match="saldo pendiente"):
        ordenes.cambiar_estado(conn, empleado, orden, "entregada")
    ef = _id(conn, "metodos_pago", "Efectivo")
    caja.registrar_pago(conn, empleado, orden, ef, 200)
    ordenes.cambiar_estado(conn, empleado, orden, "entregada")
    assert caja.resumen_corte(conn)["efectivo_esperado"] == 200  # lo rechazado no mueve efectivo


def test_pago_mixto_efectivo_mas_transferencia_pendiente(conn, empleado, orden):
    ef, tr = _id(conn, "metodos_pago", "Efectivo"), _id(conn, "metodos_pago", "Transferencia")
    caja.registrar_pago(conn, empleado, orden, ef, 50)
    caja.registrar_pago(conn, empleado, orden, tr, 150, referencia="X9")
    o = ordenes.obtener_orden(conn, orden)
    assert o["saldo"] == 0 and o["por_confirmar"] == 150
