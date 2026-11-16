"""La aplicación de escritorio, sin pantalla (Qt offscreen) y contra la base de pruebas."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from oceanica.app import dialogos  # noqa: E402
from oceanica.app.aplicacion import preparar_aplicacion  # noqa: E402
from oceanica.app.carrito import Carrito  # noqa: E402
from oceanica.app.contexto import Contexto  # noqa: E402
from oceanica.app.ventana import Ventana  # noqa: E402
from oceanica.servicios import caja, catalogo, clientes, configuracion, ordenes, usuarios  # noqa: E402

D = Decimal


@pytest.fixture(scope="module")
def qapp():
    app = preparar_aplicacion()
    yield app
    from PySide6.QtWidgets import QApplication
    for w in QApplication.topLevelWidgets():  # evita cierres bruscos de Qt al terminar el intérprete
        w.close()
        w.deleteLater()
    app.processEvents()


# ---------- carrito (sin base de datos) -----------------------------------------

def test_carrito_totales_y_validaciones():
    c = Carrito()
    kilo = {"id": 1, "nombre": "Lavado", "unidad": "kilo", "precio": D("28.50")}
    pieza = {"id": 2, "nombre": "Edredón", "unidad": "pieza", "precio": D("120")}
    c.agregar(kilo, D("3.5"))
    c.agregar(kilo, D("1"))  # mismo servicio: se suma
    c.agregar(pieza, D("2"))
    assert len(c.lineas) == 2 and c.subtotal == D("128.25") + D("240")
    c.descuento = D("10")
    assert c.total == D("358.25")
    for malo in (None, D("0"), D("-1")):
        with pytest.raises(ValueError):
            c.agregar(kilo, malo)
    with pytest.raises(ValueError, match="entero"):
        c.agregar(pieza, D("1.5"))
    assert c.items() == [{"servicio_id": 1, "cantidad": D("4.50")}, {"servicio_id": 2, "cantidad": D("2.00")}]
    c.quitar(0)
    assert len(c.lineas) == 1
    c.sumar(0, 1)
    assert c.lineas[0].cantidad == D("3")
    with pytest.raises(ValueError, match="entero"):
        c.fijar(0, D("2.5"))
    c.fijar(0, D("1"))
    c.sumar(0, -1)                                   # llega a cero: se quita la línea
    assert not c


# ---------- con base de datos -----------------------------------------------------

@pytest.fixture()
def mundo(conn, admin, empleado):
    cats = catalogo.listar_categorias(conn)
    kilo = catalogo.crear_servicio(conn, admin, cats[0]["id"], "Lavado y secado", "kilo", "28.50")
    pieza = catalogo.crear_servicio(conn, admin, cats[1]["id"], "Edredón", "pieza", 120)
    uid = usuarios.alta_empleado_con_acceso(conn, admin, "Luis", "Mora", "2026-01-01", "482615")["usuario_id"]
    return {"kilo": kilo, "pieza": pieza, "uid": uid}


def _sin_dialogos(monkeypatch, pago=None):
    """Sustituye los diálogos modales: el cobro devuelve `pago` y el resto se acepta solo."""
    def cobro_exec(self):
        self.pago = pago
        return True
    monkeypatch.setattr(dialogos.CobroDialog, "exec", cobro_exec)
    monkeypatch.setattr(dialogos.TicketDialog, "exec", lambda self: 1)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: pytest.fail(f"Advertencia inesperada: {a[2]}"))
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: pytest.fail(f"Error inesperado: {a[2]}"))


def _elegir(monkeypatch, boton: str):
    """Los cuadros con botones propios (QMessageBox.exec) se resuelven pulsando el botón con ese texto."""
    monkeypatch.setattr(QMessageBox, "exec", lambda self: setattr(self, "_texto", boton) or 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: next(b for b in self.buttons() if b.text() == self._texto))


def test_todas_las_pantallas_abren(qapp, conn, admin, mundo):
    ctx = Contexto(conn)
    v = Ventana(ctx)
    v.abrir_shell(admin)
    assert [p.titulo for p in v.paginas] == ["Nueva orden", "Órdenes", "Caja", "Clientes", "Asistencia",
                                             "Inventario", "Panel del negocio", "Reportes", "Nómina", "Servicios y precios", "Empleados y usuarios",
                                             "Transferencias", "Configuración"]
    for i in range(len(v.paginas)):
        v.nav.setCurrentRow(i)
        qapp.processEvents()
    v.cerrar_sesion()
    v.abrir_shell(None)  # modo mostrador: sin pantallas de administración
    assert [p.titulo for p in v.paginas] == ["Nueva orden", "Órdenes", "Caja", "Clientes", "Asistencia", "Inventario"]
    assert ctx.admin is None
    v.mostrar_login()
    v.close()


def test_flujo_completo_por_pantalla(qapp, conn, admin, empleado, mundo, monkeypatch):
    _sin_dialogos(monkeypatch)
    ctx = Contexto(conn)  # modo mostrador: cada acción se identifica con PIN (aquí, simulado)
    pedidos = []
    ctx.identificar = lambda parent, sensible=True, titulo="": pedidos.append(sensible) or empleado
    caja.abrir_corte(conn, admin, 100)
    ef = [m for m in caja.listar_metodos(conn) if m["es_efectivo"]][0]["id"]

    # --- capturar la orden como lo haría el empleado: buscar, cantidad, Enter
    from oceanica.app.v_mostrador import MostradorView
    m = MostradorView(ctx)
    m.al_mostrar()
    m.filtro.setText("lavado")                       # búsqueda sin acentos ni mayúsculas
    assert [s["nombre"] for s in m.visibles] == ["Lavado y secado"]
    m.filtro.setText("edredon")                      # sin acento encuentra «Edredón»
    assert [s["nombre"] for s in m.visibles] == ["Edredón"]
    m.filtro.setText("tintoreria")                   # la búsqueda es solo por nombre del servicio
    assert m.visibles == []
    m.filtro.setText("")
    assert m.pila.currentIndex() == 0                # sin búsqueda vuelve a los botones de categorías
    # piezas: abrir la categoría y tocar la opción (cada toque es una pieza; ＋/－ ajustan)
    planchado = next(c for c in m.categorias if c["nombre"] == "Planchado")
    m.abrir_categoria(planchado)
    assert [s["nombre"] for s in m.visibles] == ["Edredón"]
    m.elegir(m.visibles[0])
    m.elegir(m.visibles[0])
    assert m.lb_total.text() == "$240.00"
    m.tabla_carrito.selectRow(0)
    m._sumar(-1)                                     # «Quitar 1»: queda una pieza
    assert m.carrito.lineas[0].cantidad == 1
    preguntas = []
    m.preguntar_eliminar = lambda nombre, cant: preguntas.append((nombre, cant)) or False
    m._sumar(-1)                                     # la última pieza: pide confirmación y aquí dice «No»
    assert preguntas == [("Edredón", "1 pieza")] and len(m.carrito.lineas) == 1
    m.elegir(m.visibles[0])
    m.elegir(m.visibles[0])
    m.tabla_carrito.selectRow(0)
    m._quitar()                                      # «Eliminar» todo el servicio: también pregunta
    assert preguntas[-1] == ("Edredón", "3 piezas") and len(m.carrito.lineas) == 1
    m.preguntar_eliminar = lambda nombre, cant: True
    m._quitar()
    assert not m.carrito
    # ropa por kilo: el botón grande abre el teclado (aquí simulado) con los kilos de la báscula
    m.pedir_kilos = lambda servicio, actual=None: D("3") if actual is None else D("4")
    m.abrir_kilo()
    assert m.lb_total.text() == "$85.50"
    m.tabla_carrito.selectRow(0)
    assert m.b_menos.text() == "Cambiar kilos" and not m.b_mas.isVisibleTo(m)
    m._sumar(-1)                                     # en kilos, «Cambiar kilos» abre el teclado para corregir
    assert m.lb_total.text() == "$114.00"
    cid = clientes.crear_cliente(conn, admin, "Ana", "Torres", "5511112222")
    m.cliente_id = cid
    _sin_dialogos(monkeypatch, pago={"metodo_pago_id": ef, "monto": D("50"), "referencia": None})
    m.guardar()
    assert not m.carrito  # se limpió para la siguiente orden
    o = ordenes.listar_ordenes(conn)[0]
    assert o["folio"] == "OC-000001" and o["saldo"] == D("64.00") and o["cliente"] == "Ana Torres"
    assert ordenes.obtener_orden(conn, o["id"])["recibio"] == "cajero"  # quedó a nombre del empleado

    # --- seguimiento, cobro del saldo y entrega desde la pantalla de órdenes
    from oceanica.app.v_ordenes import OrdenesView
    ov = OrdenesView(ctx)
    ov.al_mostrar()
    assert ov.tabla.rowCount() == 1
    ov.tabla.selectRow(0)
    ov.avanzar()  # en proceso
    ov.avanzar()  # lista
    assert ordenes.obtener_orden(conn, o["id"])["estado"] == "lista"
    _sin_dialogos(monkeypatch, pago={"metodo_pago_id": ef, "monto": D("64"), "referencia": None})
    _elegir(monkeypatch, "Cobrar ahora")
    ov.entregar()  # saldo pendiente: ofrece cobrar (acepta) y luego entrega
    final = ordenes.obtener_orden(conn, o["id"])
    assert final["estado"] == "entregada" and final["saldo"] == 0
    assert all(p["estado_confirmacion"] == "confirmado" for p in final["pagos"])
    assert pedidos == [True, False, False, True, True]  # guardar, avanzar x2 (no sensible), cobrar y entregar


def test_mostrador_sin_caja_no_cobra_anticipo(qapp, conn, admin, mundo, monkeypatch):
    avisos = []
    _sin_dialogos(monkeypatch, pago={"metodo_pago_id": 1, "monto": D("10"), "referencia": None})
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: avisos.append(a[2]))
    ctx = Contexto(conn)
    ctx.admin = admin
    from oceanica.app.v_mostrador import MostradorView
    m = MostradorView(ctx)
    m.al_mostrar()
    m.agregar(m.servicios[0], D("2"))
    m.guardar()
    assert any("No hay caja abierta" in a for a in avisos)
    assert ordenes.listar_ordenes(conn) == []  # no se creó nada


def test_pin_dialog_valida_y_bloquea(qapp, conn, mundo):
    ctx = Contexto(conn)
    dlg = dialogos.PinDialog(ctx, None)
    assert dlg.combo.count() == 1
    dlg.pin.setText("000999")
    dlg._aceptar()
    assert dlg.sesion is None and "incorrectos" in dlg.msg.text()
    dlg.pin.setText("482615")
    dlg._aceptar()
    assert dlg.sesion["rol"] == "empleado"


def test_cobro_dialog_reglas(qapp, conn, mundo):
    from oceanica.app.cobro import P_EFECTIVO, P_METODO, P_PARTE, sugerencias_billetes
    ctx = Contexto(conn)
    ef = [m for m in caja.listar_metodos(conn) if m["es_efectivo"]][0]["id"]
    tr = [m for m in caja.listar_metodos(conn) if m["requiere_confirmacion"]][0]["id"]
    # paga solo una parte: no puede ser más que el saldo
    d = dialogos.CobroDialog(ctx, None, D("100"), "Cobro", permite_cero=False)
    assert not d.b_despues.isVisibleTo(d)              # «al recoger» solo existe al crear la orden
    d.elegir_modo("parte")
    assert d.pila.currentIndex() == P_PARTE
    d.teclado_parte.pantalla.setText("150")
    d.confirmar_parte()
    assert "No puede ser más" in d.msg.text()
    d.teclado_parte.pantalla.setText("40")
    assert "60.00" in d.lb_resto.text()
    d.confirmar_parte()
    assert d.pila.currentIndex() == P_METODO
    d.elegir_metodo(ef)
    assert d.pila.currentIndex() == P_EFECTIVO
    d.recibido.setText("20")
    d._aceptar()
    assert d.pago is None and "menos" in d.msg.text()
    d.recibido.setText("50")
    assert d.lb_cambio.text() == "Cambio: $10.00"
    d._aceptar()
    assert d.pago == {"metodo_pago_id": ef, "monto": D("40.00"), "referencia": None}
    # transferencia: exige la captura o la clave de rastreo
    t = dialogos.CobroDialog(ctx, None, D("100"), "Cobro", permite_cero=False)
    t.elegir_modo("todo")
    t.elegir_metodo(tr)
    t._aceptar()
    assert t.pago is None and "captura" in t.msg.text()
    t.referencia.setText("MBAN1")
    t._aceptar()
    assert t.pago == {"metodo_pago_id": tr, "monto": D("100"), "referencia": "MBAN1"}
    # al crear la orden se puede dejar todo para cuando recoja
    e = dialogos.CobroDialog(ctx, None, D("100"), "Anticipo", permite_cero=True)
    e.elegir_modo("despues")
    assert e.pago is None and e.result() == 1
    # «Atrás» regresa al paso anterior
    a = dialogos.CobroDialog(ctx, None, D("100"), "Anticipo", permite_cero=True)
    a.elegir_modo("todo")
    a.atras()
    assert a.pila.currentIndex() == 0
    assert sugerencias_billetes(D("126")) == [D(150), D(200), D(500), D(1000)]


def test_inventario_por_pantalla(qapp, conn, admin, empleado, mundo, monkeypatch):
    from oceanica.app import v_inventario
    from oceanica.servicios import inventario
    _sin_dialogos(monkeypatch)
    cat = inventario.listar_categorias(conn)[0]["id"]
    inventario.crear_insumo(conn, admin, cat, "Detergente", "litro", 10, 25, None, 4)
    ctx = Contexto(conn)
    ctx.admin = admin
    vista = v_inventario.InventarioView(ctx)
    vista.al_mostrar()
    assert vista.tabla.rowCount() == 1
    assert vista.tabla.item(0, 6).text() == "BAJO"
    vista.tabla.selectRow(0)

    # entrada de 20 litros confirmada con PIN (simulado)
    ctx.identificar = lambda *a, **k: empleado
    monkeypatch.setattr(v_inventario.MovimientoDialog, "exec", lambda self: (self.cantidad.setText("20"), True)[1])
    vista.mover("entrada")
    assert vista.tabla.item(0, 2).text().startswith("24")
    assert vista.tabla.item(0, 6).text() == "OK"

    # salida mayor a la existencia: el servicio la rechaza y se avisa
    avisos = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: avisos.append(a[2]))
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: avisos.append(a[2]))
    monkeypatch.setattr(v_inventario.MovimientoDialog, "exec", lambda self: (self.cantidad.setText("999"), True)[1])
    vista.mover("salida")
    assert avisos and vista.tabla.item(0, 2).text().startswith("24")

    # ajuste al conteo físico (admin)
    def ajuste(self):
        self.cantidad.setText("7")
        self.motivo.setText("Conteo mensual")
        return True
    monkeypatch.setattr(v_inventario.MovimientoDialog, "exec", ajuste)
    vista.ajustar()
    assert vista.tabla.item(0, 2).text().startswith("7")
    assert vista.tabla.item(0, 6).text() == "BAJO"
    vista.solo_bajos.setChecked(True)
    assert vista.tabla.rowCount() == 1
    vista.close()


def test_reportes_por_pantalla_y_exportacion(qapp, conn, admin, mundo, monkeypatch, tmp_path):
    from datetime import date
    from oceanica.app import v_reportes
    _sin_dialogos(monkeypatch)
    ctx = Contexto(conn)
    ctx.admin = admin
    vista = v_reportes.ReportesView(ctx)
    vista.al_mostrar()
    for i in range(vista.selector.count()):  # cada reporte se pinta sin errores
        vista.selector.setCurrentIndex(i)
        assert vista.tabla.columnCount() == len(vista.reporte["columnas"])
    assert vista.kpi["ordenes"].text() == "0"

    vista.selector.setCurrentIndex(0)
    for formato in ("xlsx", "pdf"):
        destino = tmp_path / f"r.{formato}"
        monkeypatch.setattr(v_reportes.QFileDialog, "getSaveFileName", lambda *a, **k: (str(destino), ""))
        monkeypatch.setattr(v_reportes.QDesktopServices, "openUrl", lambda *a: True)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
        vista.exportar()
        assert destino.exists() and destino.stat().st_size > 500

    d, h = v_reportes.rango_periodo("Mes pasado", date(2026, 3, 15))
    assert (d, h) == (date(2026, 2, 1), date(2026, 2, 28))
    assert v_reportes.rango_periodo("Esta semana", date(2026, 11, 5))[0] == date(2026, 11, 2)
    vista.close()


def _orden_lista(conn, admin, empleado, mundo, pagos=()):
    """Orden de 2 edredones ($240) lista para entregar; `pagos` = [(método, monto, referencia)]."""
    caja.abrir_corte(conn, admin, 100)
    oid = ordenes.crear_orden(conn, empleado, [{"servicio_id": mundo["pieza"], "cantidad": 2}])
    for metodo, monto, ref in pagos:
        mid = [m for m in caja.listar_metodos(conn) if m["nombre"] == metodo][0]["id"]
        caja.registrar_pago(conn, empleado, oid, mid, monto, referencia=ref)
    ordenes.cambiar_estado(conn, empleado, oid, "en_proceso")
    ordenes.cambiar_estado(conn, empleado, oid, "lista")
    return oid


def _vista_ordenes(conn, empleado, monkeypatch):
    from oceanica.app.v_ordenes import OrdenesView
    _sin_dialogos(monkeypatch)
    ctx = Contexto(conn)
    ctx.identificar = lambda *a, **k: empleado
    ov = OrdenesView(ctx)
    ov.al_mostrar()
    ov.tabla.selectRow(0)
    return ctx, ov


def test_entrega_con_saldo_autorizada_por_la_encargada(qapp, conn, admin, empleado, mundo, monkeypatch):
    oid = _orden_lista(conn, admin, empleado, mundo)
    ctx, ov = _vista_ordenes(conn, empleado, monkeypatch)
    _elegir(monkeypatch, "Pedir autorización de la encargada")
    ctx.autorizar_admin = lambda *a, **k: None            # la encargada no se identifica
    ov.entregar()
    assert ordenes.obtener_orden(conn, oid)["estado"] == "lista"
    ctx.autorizar_admin = lambda *a, **k: admin           # la encargada autoriza y da el motivo
    monkeypatch.setattr("oceanica.app.v_ordenes.QInputDialog.getText", lambda *a, **k: ("Cliente de confianza, paga mañana", True))
    ov.entregar()
    o = ordenes.obtener_orden(conn, oid)
    assert o["estado"] == "entregada" and o["saldo"] == D("240.00")
    nota = o["historial"][-1]["nota"]
    assert "Autorizó admin, entregó cajero" in nota and "paga mañana" in nota


def test_entrega_con_transferencia_por_confirmar_pide_a_la_encargada(qapp, conn, admin, empleado, mundo, monkeypatch):
    oid = _orden_lista(conn, admin, empleado, mundo, [("Transferencia", D("240"), "CAPTURA DE PANTALLA")])
    assert configuracion.obtener(conn, "entrega_transferencia_pendiente") == "admin"
    ctx, ov = _vista_ordenes(conn, empleado, monkeypatch)
    ctx.autorizar_admin = lambda *a, **k: None
    ov.entregar()                                         # sin autorización no sale la ropa
    assert ordenes.obtener_orden(conn, oid)["estado"] == "lista"
    ctx.autorizar_admin = lambda *a, **k: admin
    ov.entregar()
    o = ordenes.obtener_orden(conn, oid)
    assert o["estado"] == "entregada" and "transferencia por confirmar" in o["historial"][-1]["nota"]


def test_cobro_con_transferencia_acepta_captura_de_pantalla(qapp, conn, mundo):
    ctx = Contexto(conn)
    tr = [m for m in caja.listar_metodos(conn) if m["requiere_confirmacion"]][0]["id"]
    dlg = dialogos.CobroDialog(ctx, None, D("100"), "Cobrar", permite_cero=False)
    dlg.elegir_modo("todo")
    dlg.elegir_metodo(tr)
    dlg._aceptar()
    assert dlg.pago is None and "captura" in dlg.msg.text().lower()   # sin comprobante no se acepta
    dlg.captura.setChecked(True)
    dlg._aceptar()
    assert dlg.pago["referencia"] == "CAPTURA DE PANTALLA"


def test_nomina_por_pantalla_de_la_semana_al_recibo(qapp, conn, admin, mundo, monkeypatch, tmp_path):
    from datetime import date, datetime, timedelta
    from oceanica.app import v_nomina
    from oceanica.servicios import empleados, nomina
    _sin_dialogos(monkeypatch)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(v_nomina, "RAIZ", tmp_path)
    monkeypatch.setattr(v_nomina.QDesktopServices, "openUrl", lambda *a: True)
    hoy = date.today()
    lunes = hoy - timedelta(days=hoy.weekday() + 7)             # lunes de la semana pasada
    eid = empleados.crear_empleado(conn, admin, "Ana", "Prueba", "2020-01-01")
    empleados.definir_turnos(conn, admin, eid, [(d, "09:00", "15:00") for d in range(1, 7)], "2020-01-01")
    for i in range(4):                                            # trabajó lunes a jueves
        d = lunes + timedelta(days=i)
        empleados.corregir_asistencia(conn, admin, eid, d, datetime.combine(d, datetime.min.time()).replace(hour=9),
                                      datetime.combine(d, datetime.min.time()).replace(hour=15), "Captura")
    ctx = Contexto(conn)
    ctx.admin = admin
    vista = v_nomina.NominaView(ctx)
    vista.al_mostrar()
    assert vista.selector.count() == 0 and not vista.b_calcular.isEnabled()

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getItem", lambda *a, **k: (list(a[3])[1], True))
    vista.abrir_semana()                                          # semana pasada, sueldo mínimo automático
    assert vista.selector.count() == 1 and vista.b_calcular.isEnabled() and not vista.b_pagar.isEnabled()
    vista.calcular()
    assert vista.tabla.rowCount() == 2                            # Ana y Luis (que no trabajó)
    r = [i for i in range(2) if vista.tabla.item(i, 0).text() == "Ana Prueba"][0]
    assert vista.tabla.item(r, 1).text() == "4" and vista.tabla.item(r, 4).text() == "$1,260.16"   # 4 x 315.04
    vista.tabla.selectRow(r)
    vista.aprobar()
    assert vista.b_pagar.isEnabled() and not vista.b_calcular.isEnabled()

    caja.abrir_corte(conn, admin, 5000)
    monkeypatch.setattr(v_nomina.PagoDialog, "exec", lambda self: (self.firmado.setChecked(True), True)[1])
    vista.pagar()
    assert "Efectivo" in vista.tabla.item(r, 5).text() and "firmado" in vista.tabla.item(r, 5).text()
    assert caja.resumen_corte(conn)["gastos"] == D("1260.16")
    vista.recibo()
    assert any((tmp_path / "recibos").glob("*.pdf"))
    assert vista.b_cerrar.isEnabled()
    vista.cerrar()
    assert vista.chip_estado.text() == "Cerrada" and not vista.b_pagar.isEnabled()
    vista.close()


def test_horarios_y_ajustes_de_asistencia(qapp, conn, admin, empleado, mundo, monkeypatch):
    from datetime import date
    from oceanica.app import v_asistencia, v_personal
    from oceanica.servicios import empleados
    _sin_dialogos(monkeypatch)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    ctx = Contexto(conn)
    ctx.admin = admin
    pv = v_personal.PersonalView(ctx)
    pv.al_mostrar()
    fila = [r for r in range(pv.tabla.rowCount()) if "Luis" in pv.tabla.item(r, 0).text()][0]
    pv.tabla.selectRow(fila)
    assert pv.tabla.item(fila, 4).text() == "Sin horario"

    def aceptar_plantilla(self):
        self.plantilla("12:00", "18:00")
        self.filas[1][0].setChecked(False)                       # descansa los martes
        return True
    monkeypatch.setattr(v_personal.HorarioDialog, "exec", aceptar_plantilla)
    pv.horario()
    emp = [e for e in empleados.listar_empleados(conn) if e["nombre"] == "Luis"][0]
    turnos = {t["dia_semana"]: (t["hora_entrada"].hour, t["hora_salida"].hour) for t in empleados.turnos_vigentes(conn, emp["id"])}
    assert set(turnos) == {1, 3, 4, 5, 6} and turnos[1] == (12, 18) and turnos[6] == (9, 17)
    assert "Mar" not in pv.tabla.item(fila, 4).text() and "Sáb" in pv.tabla.item(fila, 4).text()

    # la encargada autoriza horas extra de hoy desde Asistencia
    hoy = date.today()
    empleados.corregir_asistencia(conn, admin, emp["id"], hoy, datetime_(hoy, 12), datetime_(hoy, 19), "Captura")
    av = v_asistencia.AsistenciaView(ctx)
    av.al_mostrar()

    def dlg_extra(self):
        self.empleado.setCurrentIndex(self.empleado.findData(emp["id"]))
        self.accion.setCurrentIndex(self.accion.findData("extra"))
        self.horas.setText("1.5")
        self.motivo.setText("Autoriza Ara")
        return True
    monkeypatch.setattr(v_asistencia.AjusteDialog, "exec", dlg_extra)
    av.ajustes()
    assert empleados.listar_asistencias(conn, hoy, hoy, emp["id"])[0]["horas_extra"] == D("1.50")
    # sin identificarse la encargada, no se guarda nada
    ctx.admin = None
    ctx.autorizar_admin = lambda *a, **k: None
    monkeypatch.setattr(v_asistencia.AjusteDialog, "exec", lambda self: (dlg_extra(self), self.horas.setText("3"), True)[2])
    av.ajustes()
    assert empleados.listar_asistencias(conn, hoy, hoy, emp["id"])[0]["horas_extra"] == D("1.50")


def datetime_(dia, hora):
    from datetime import datetime
    return datetime(dia.year, dia.month, dia.day, hora)


def test_cambiar_de_seccion_no_abre_ventanitas_sueltas(qapp, conn, admin, mundo):
    """Ningún botón o etiqueta debe aparecer un instante como ventana propia al cambiar de sección."""
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QDialog

    v = Ventana(Contexto(conn))
    sueltas = []

    class Vigia(QObject):
        def eventFilter(self, o, e):
            if (e.type() == QEvent.Show and o.isWidgetType() and o.isWindow() and o is not v
                    and not isinstance(o, QDialog) and not o.inherits("QMenu")
                    and not o.inherits("QAbstractItemView")):  # listas de sugerencias del autocompletado
                sueltas.append(type(o).__name__)
            return False

    vigia = Vigia()
    qapp.installEventFilter(vigia)
    try:
        v.show()
        v.abrir_shell(admin)
        for i in list(range(len(v.paginas))) + [0, 3, 0]:
            v.nav.setCurrentRow(i)
            qapp.processEvents()
    finally:
        qapp.removeEventFilter(vigia)
        v.cerrar_sesion()
        v.close()
    assert sueltas == []


def test_mostrador_servicio_a_domicilio(qapp, conn, admin, empleado, mundo, monkeypatch):
    _sin_dialogos(monkeypatch)
    configuracion.establecer(conn, admin, "cargo_domicilio", "30")
    try:
        ctx = Contexto(conn)
        ctx.identificar = lambda *a, **k: empleado
        from oceanica.app.v_mostrador import MostradorView
        m = MostradorView(ctx)
        m.al_mostrar()
        m.agregar(next(s for s in m.servicios if s["unidad"] == "pieza"), D("1"))   # Edredón $120
        m.elegir_entrega("domicilio")
        assert m.cargo.isReadOnly() and m.lb_total.text() == "$150.00"            # el empleado no cambia el cargo
        avisos = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: avisos.append(a[2]))
        m.guardar()
        assert avisos and "dirección" in avisos[0] and ordenes.listar_ordenes(conn) == []
        m.direccion.setText("Calle Pino 4, Col. Centro")
        m.guardar()
        o = ordenes.obtener_orden(conn, ordenes.listar_ordenes(conn)[0]["id"])
        assert o["tipo_entrega"] == "domicilio" and o["total"] == D("150.00")
        assert m.b_recoge.isChecked() and not m.p_domicilio.isVisibleTo(m)       # la siguiente orden vuelve a mostrador
    finally:
        configuracion.establecer(conn, admin, "cargo_domicilio", "0")
