"""Un día completo de operación, de abrir la caja al respaldo, comparado contra una «libreta».

La prueba lleva sus propias cuentas a mano (la libreta) con aritmética independiente del sistema y al final
exige que el corte, los saldos y los reportes coincidan con ella al centavo. Es el ensayo automático del
día de prueba en el local: 20 órdenes, efectivo y transferencias, entregas autorizadas, una transferencia
rechazada, una cancelación, gastos, retiro, pago de nómina, corte a ciegas y respaldo con restauración.
"""
import shutil
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

import pytest

from oceanica import respaldos, seguridad
from oceanica.servicios import (avisos, caja, catalogo, clientes, configuracion, empleados, nomina, ordenes, reportes,
                                tickets, usuarios)
from oceanica.servicios.comunes import ErrorNegocio

from .conftest import _CFG

D = Decimal
PRECIO_KILO, PRECIO_PIEZA, CARGO_DOMICILIO, FONDO = D("28.50"), D("120.00"), D("35.00"), D("500.00")
SALARIO = D("315.04")


def _centavos(valor: Decimal) -> Decimal:
    return valor.quantize(D("0.01"), rounding=ROUND_HALF_UP)


class Libreta:
    """Las cuentas a mano de la encargada: no consulta al sistema para nada."""

    def __init__(self):
        self.efectivo = FONDO                 # lo que debe haber en el cajón
        self.total: dict[int, Decimal] = {}   # orden -> total
        self.pagado: dict[int, Decimal] = {}  # orden -> pagado (efectivo + transferencias no rechazadas)
        self.transf_pendientes: dict[int, Decimal] = {}
        self.canceladas: set[int] = set()
        self.gastos = self.retiros = self.ingresos = D(0)

    def orden(self, n, total):
        self.total[n], self.pagado[n] = total, D(0)

    def cobro_efectivo(self, n, monto):
        self.efectivo += monto
        self.pagado[n] += monto

    def cobro_transferencia(self, n, monto):
        self.pagado[n] += monto
        self.transf_pendientes[n] = monto

    def saldo(self, n):
        return self.total[n] - self.pagado[n]

    @property
    def vendido(self):
        return sum((t for n, t in self.total.items() if n not in self.canceladas), D(0))

    @property
    def por_cobrar(self):
        return sum((self.saldo(n) for n in self.total if n not in self.canceladas), D(0))


@pytest.fixture()
def negocio(conn, admin):
    """Catálogo, cargo a domicilio y tres empleados con PIN, como estará el local el primer día."""
    cats = catalogo.listar_categorias(conn)
    kilo = catalogo.crear_servicio(conn, admin, cats[0]["id"], "Ropa por kilo", "kilo", PRECIO_KILO)
    pieza = catalogo.crear_servicio(conn, admin, cats[1]["id"], "Edredón", "pieza", PRECIO_PIEZA)
    configuracion.establecer(conn, admin, "cargo_domicilio", str(CARGO_DOMICILIO))
    personal = []
    for nombre, pin in (("Ana", "482615"), ("Beto", "739104"), ("Caro", "260958")):
        alta = usuarios.alta_empleado_con_acceso(conn, admin, nombre, "Prueba", "2026-01-01", pin)
        sesion = seguridad.autenticar_pin(conn, alta["usuario_id"], pin)
        personal.append({"sesion": sesion, "empleado_id": alta["empleado_id"], "nombre": nombre})
    metodos = {("efectivo" if m["es_efectivo"] else m["nombre"].lower()): m["id"] for m in caja.listar_metodos(conn)}
    yield {"kilo": kilo, "pieza": pieza, "personal": personal, "efectivo": metodos["efectivo"],
           "transferencia": metodos["transferencia"]}
    configuracion.establecer(conn, admin, "cargo_domicilio", "0")


def test_un_dia_completo_cuadra_con_la_libreta(conn, admin, negocio, tmp_path, monkeypatch):
    lib = Libreta()
    ana, beto, caro = (p["sesion"] for p in negocio["personal"])
    hoy = date.today()
    oid: dict[int, int] = {}

    # ---- 8:55 llegan, 9:00 abren la caja --------------------------------------------------------
    for p in negocio["personal"]:
        empleados.registrar_entrada(conn, p["sesion"], p["empleado_id"], datetime.combine(hoy, datetime.min.time()).replace(hour=9))
    caja.abrir_corte(conn, ana, FONDO)

    # ---- durante el día: 20 órdenes -------------------------------------------------------------
    for n in range(1, 21):
        quien = (ana, beto, caro)[n % 3]
        cid = clientes.crear_cliente(conn, quien, f"Cliente{n}", "Prueba", f"55{n:08d}")
        if n % 2:                                    # impares: ropa por kilo con medio kilo
            cantidad = D(2) + D(n) / 2
            importe = _centavos(PRECIO_KILO * cantidad)
            items = [{"servicio_id": negocio["kilo"], "cantidad": cantidad}]
        else:                                        # pares: edredones por pieza
            cantidad = 1 + n % 3
            importe = PRECIO_PIEZA * cantidad
            items = [{"servicio_id": negocio["pieza"], "cantidad": cantidad}]
        domicilio = n % 5 == 0
        total = importe + (CARGO_DOMICILIO if domicilio else 0)
        lib.orden(n, total)
        anticipo = None
        if n % 4 == 1:                               # paga todo en efectivo al dejar la ropa
            anticipo = {"metodo_pago_id": negocio["efectivo"], "monto": total}
            lib.cobro_efectivo(n, total)
        elif n % 4 == 2:                             # deja $50 de anticipo
            anticipo = {"metodo_pago_id": negocio["efectivo"], "monto": D("50")}
            lib.cobro_efectivo(n, D("50"))
        elif n % 4 == 3:                             # transfiere todo y enseña la captura
            anticipo = {"metodo_pago_id": negocio["transferencia"], "monto": total, "referencia": "CAPTURA DE PANTALLA"}
            lib.cobro_transferencia(n, total)
        oid[n] = ordenes.crear_orden(
            conn, quien, items, cliente_id=cid, anticipo=anticipo, requiere_factura=(n == 6),
            entrega={"tipo": "domicilio", "direccion": f"Calle {n}, Centro"} if domicilio else None)
        o = ordenes.obtener_orden(conn, oid[n])
        assert (o["total"], o["saldo"]) == (total, lib.saldo(n)), f"orden {n}"
        assert tickets.ticket_orden_texto(conn, oid[n])              # el ticket se arma sin error

    # movimientos de caja del día
    caja.registrar_movimiento(conn, beto, "gasto", "Jabón y suavizante", D("185.50"))
    caja.registrar_movimiento(conn, caro, "ingreso", "Cambio que trajo la encargada", D("200"))
    with pytest.raises(Exception):
        caja.registrar_movimiento(conn, caro, "retiro", "Me llevo dinero", D("100"))   # el retiro es solo de la encargada
    caja.registrar_movimiento(conn, admin, "retiro", "Depósito al banco", D("1000"))
    lib.efectivo += D("200") - D("185.50") - D("1000")

    # la ropa pasa a proceso y queda lista; se avisa a tres clientes
    for n in range(1, 21):
        ordenes.cambiar_estado(conn, beto, oid[n], "en_proceso")
        ordenes.cambiar_estado(conn, beto, oid[n], "lista")
    for n in (1, 2, 3):
        assert f"5{n:09d}"[-8:] in avisos.aviso_orden_lista(conn, oid[n])["enlace"]
        avisos.registrar_aviso(conn, caro, oid[n])

    # ---- entregas -------------------------------------------------------------------------------
    for n in (1, 5, 9, 13, 17):                      # pagadas en efectivo: se entregan sin más
        ordenes.cambiar_estado(conn, ana, oid[n], "entregada")

    for n in (6, 10, 14, 18):                        # con anticipo: pagan el resto en efectivo y se entregan
        with pytest.raises(ErrorNegocio, match="saldo pendiente"):
            ordenes.cambiar_estado(conn, ana, oid[n], "entregada")
        resto = lib.saldo(n)
        with pytest.raises(ErrorNegocio, match="excede"):
            caja.registrar_pago(conn, ana, oid[n], negocio["efectivo"], resto + D("0.01"))   # nunca más que el saldo
        caja.registrar_pago(conn, ana, oid[n], negocio["efectivo"], resto)
        lib.cobro_efectivo(n, resto)
        ordenes.cambiar_estado(conn, ana, oid[n], "entregada")

    # la 2 no trae para el resto: el empleado no puede entregar ni forzar; la encargada autoriza con motivo
    with pytest.raises(ErrorNegocio):
        ordenes.cambiar_estado(conn, ana, oid[2], "entregada", "paga mañana", True)
    ordenes.cambiar_estado(conn, admin, oid[2], "entregada", "Autorizó admin, entregó ana: clienta de confianza, paga mañana", True)

    # transferencias: sin confirmar, el empleado no entrega
    for n in (3, 7, 11, 15, 19):
        with pytest.raises(ErrorNegocio, match="[Tt]ransferencia"):
            ordenes.cambiar_estado(conn, beto, oid[n], "entregada")
    pendientes = {p["orden_id"]: p["id"] for p in caja.listar_transferencias_pendientes(conn, admin)}
    assert set(pendientes) == {oid[n] for n in (3, 7, 11, 15, 19)}
    for n in (3, 7, 11):                             # la encargada las ve en el banco: confirmadas y entregadas
        caja.confirmar_transferencia(conn, admin, pendientes[oid[n]])
        del lib.transf_pendientes[n]
        ordenes.cambiar_estado(conn, beto, oid[n], "entregada")
    caja.rechazar_transferencia(conn, admin, pendientes[oid[15]], "No llegó al banco")   # captura falsa o error
    lib.pagado[15] -= lib.transf_pendientes.pop(15)
    assert ordenes.obtener_orden(conn, oid[15])["saldo"] == lib.total[15]
    with pytest.raises(ErrorNegocio, match="saldo pendiente"):
        ordenes.cambiar_estado(conn, beto, oid[15], "entregada")      # la ropa no sale
    ordenes.cambiar_estado(conn, admin, oid[19], "entregada", "Autorizó admin: clienta frecuente")   # pendiente, autorizada

    # las que pagan al recoger
    for n in (4, 8):
        caja.registrar_pago(conn, caro, oid[n], negocio["efectivo"], lib.total[n])
        lib.cobro_efectivo(n, lib.total[n])
        ordenes.cambiar_estado(conn, caro, oid[n], "entregada")
    caja.registrar_pago(conn, caro, oid[12], negocio["transferencia"], lib.total[12], referencia="MBAN-778123")
    lib.cobro_transferencia(12, lib.total[12])       # se queda lista, esperando confirmación
    with pytest.raises(Exception):
        ordenes.cancelar_orden(conn, caro, oid[20], "El cliente se arrepintió")   # cancelar es de la encargada
    ordenes.cancelar_orden(conn, admin, oid[20], "El cliente se arrepintió")
    lib.canceladas.add(20)
    # la 16 se queda lista y sin pagar

    # ---- fin del día: nómina de la semana (un pago en efectivo sale de la caja) -------------------
    for p in negocio["personal"]:
        empleados.registrar_salida(conn, p["sesion"], p["empleado_id"], datetime.combine(hoy, datetime.min.time()).replace(hour=15))
    lunes_siguiente = hoy + timedelta(days=7 - hoy.weekday())
    monkeypatch.setattr(nomina, "hoy", lambda: lunes_siguiente)
    nomina.aplicar_salario_minimo(conn, admin)
    periodo = nomina.crear_periodo_semanal(conn, admin, hoy)
    nomina.calcular_periodo(conn, admin, periodo)
    nomina.aprobar_periodo(conn, admin, periodo)
    por_nombre = {x["empleado"].split()[0]: x for x in nomina.obtener_periodo(conn, admin, periodo)["nominas"]}
    assert {x["neto"] for x in por_nombre.values()} == {SALARIO}      # un día trabajado cada quien
    nomina.registrar_pago_empleado(conn, admin, por_nombre["Ana"]["id"], True, "efectivo", recibo_firmado=True)
    nomina.registrar_pago_empleado(conn, admin, por_nombre["Beto"]["id"], True, "transferencia")
    lib.efectivo -= SALARIO                           # solo el pago en efectivo sale del cajón

    # ---- corte a ciegas ---------------------------------------------------------------------------
    corte_id = caja.corte_abierto(conn)["id"]
    with pytest.raises(ErrorNegocio) as e:
        caja.cerrar_corte(conn, ana, lib.efectivo - D("20"))          # cuenta mal: no se le dice por cuánto
    assert "$" not in str(e.value)
    r = caja.cerrar_corte(conn, ana, lib.efectivo)                    # cuenta bien: cierra sin explicación
    assert r["efectivo_esperado"] == lib.efectivo and r["diferencia"] == 0
    assert r["transferencias_pendientes"] == {"cantidad": len(lib.transf_pendientes),
                                              "total": sum(lib.transf_pendientes.values())}
    assert set(lib.transf_pendientes) == {12, 19}
    assert len(caja.conteos_rechazados(conn, admin, corte_id)) == 1
    assert "DIFERENCIA" in tickets.ticket_corte_texto(conn, corte_id)
    with pytest.raises(ErrorNegocio, match="caja abierta"):
        caja.registrar_pago(conn, ana, oid[16], negocio["efectivo"], D("10"))   # caja cerrada: ya no se cobra

    # ---- lo que dicen los saldos y los reportes ----------------------------------------------------
    for n in range(1, 21):
        if n not in lib.canceladas:
            assert ordenes.obtener_orden(conn, oid[n])["saldo"] == lib.saldo(n), f"saldo de la orden {n}"
    g = reportes.resumen_general(conn, hoy, hoy)
    assert (g["ordenes"], g["vendido"], g["clientes_nuevos"]) == (19, lib.vendido, 20)
    assert g["por_cobrar"] == lib.por_cobrar          # la 2 (entregada con saldo), la 15 (rechazada) y la 16
    assert g["ordenes_abiertas"] == 3                 # 12, 15 y 16 siguen en el local
    estados = {n: ordenes.obtener_orden(conn, oid[n])["estado"] for n in range(1, 21)}
    assert [n for n, e in estados.items() if e == "lista"] == [12, 15, 16] and estados[20] == "cancelada"
    cortes = reportes.cortes_de_caja(conn, hoy, hoy)["filas"]
    assert len(cortes) == 1 and D(cortes[0]["efectivo_contado"]) == lib.efectivo
    ruta = reportes.entregas_domicilio(conn)["filas"]
    assert [f["folio"] for f in ruta] == [ordenes.obtener_orden(conn, oid[15])["folio"]]   # 5 y 10 entregadas, 20 cancelada
    assert ruta[0]["saldo"] == lib.total[15] and ruta[0]["direccion_entrega"] == "Calle 15, Centro"
    assert [f["folio"] for f in reportes.por_facturar(conn, admin, hoy, hoy)["filas"]] == [
        ordenes.obtener_orden(conn, oid[6])["folio"]]

    # ---- respaldo del día y restauración ------------------------------------------------------------
    if not (shutil.which("mysqldump") and shutil.which("mysql")):
        return
    archivo = respaldos.crear_respaldo("automatico", None, cfg=_CFG, carpeta=tmp_path)
    assert respaldos.estado(conn, carpeta=tmp_path)["nivel"] in ("aviso", "ok")
    cur = conn.cursor()
    cur.execute("SET FOREIGN_KEY_CHECKS = 0")
    for tabla in ("pagos", "ordenes", "movimientos_caja"):            # el desastre: se pierden el dinero y las órdenes
        cur.execute(f"DELETE FROM `{tabla}`")
    cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    conn.commit()
    cur.close()
    respaldos.restaurar(archivo, cfg=_CFG)
    for n in range(1, 21):
        if n not in lib.canceladas:
            assert ordenes.obtener_orden(conn, oid[n])["saldo"] == lib.saldo(n), f"tras restaurar, orden {n}"
    assert caja.resumen_corte(conn, corte_id)["efectivo_esperado"] == lib.efectivo
