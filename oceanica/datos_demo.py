"""Llena una base VACÍA con datos de ejemplo para probar el sistema (NUNCA en la computadora del cliente).

    python -m oceanica.datos_demo

Crea servicios con precios, empleados con PIN, clientes, insumos y alrededor de un año de órdenes con sus
cobros, más algunas órdenes abiertas (recibidas, en proceso, listas con saldo, a domicilio y transferencias
por confirmar). Si la base ya tiene órdenes, no hace nada: así no se mezcla con datos reales.
"""
from __future__ import annotations

import random
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal

from .config import cargar_config
from .db import aplicar_migraciones, conectar
from .servicios import caja, catalogo, clientes, configuracion, inventario, ordenes, usuarios
from .servicios.panel import MESES_LARGOS

D = Decimal

SERVICIOS = {  # categoría -> [(nombre, unidad, precio)]
    "Ropa por kilo": [("Lavado y secado", "kilo", 28)],
    "Colchas y edredones": [("Colcha individual", "pieza", 90), ("Colcha matrimonial", "pieza", 110),
                            ("Edredón individual", "pieza", 120), ("Edredón matrimonial", "pieza", 150),
                            ("Edredón king size", "pieza", 180)],
    "Cobijas": [("Cobija individual", "pieza", 80), ("Cobija matrimonial", "pieza", 100)],
    "Chamarras y abrigos": [("Chamarra", "pieza", 95), ("Abrigo largo", "pieza", 130)],
    "Cojines": [("Cojín chico", "pieza", 40), ("Cojín grande", "pieza", 60)],
    "Cortinas": [("Cortina (por pieza)", "pieza", 70)],
    "Calzado": [("Tenis", "pieza", 80), ("Botas", "pieza", 110)],
    "Planchado": [("Camisa", "pieza", 22), ("Pantalón", "pieza", 22), ("Vestido", "pieza", 35)],
    "Estilo tintorería": [("Traje 2 piezas", "pieza", 180), ("Vestido de fiesta", "pieza", 220),
                          ("Saco", "pieza", 110)],
}
EMPLEADOS = [("Rosa", "Martínez", "482615", "Mostrador"), ("Jorge", "Ramírez", "739164", "Lavado"),
             ("Patricia", "Gómez", "516273", "Mostrador")]
CLIENTES = [("María", "López"), ("José", "García"), ("Guadalupe", "Hernández"), ("Juan", "Martínez"),
            ("Rosa", "Pérez"), ("Carlos", "Sánchez"), ("Laura", "Ramírez"), ("Miguel", "Flores"),
            ("Ana", "Torres"), ("Luis", "Mora"), ("Verónica", "Cruz"), ("Fernando", "Ortiz"),
            ("Alejandra", "Reyes"), ("Ricardo", "Vargas"), ("Sofía", "Castillo"), ("Jorge", "Mendoza"),
            ("Teresa", "Aguilar"), ("Héctor", "Navarro"), ("Patricia", "Romero"), ("Arturo", "Salinas")]
CALLES = ["Av. Hidalgo 45, Col. Centro", "Calle Pino 12, Col. Las Flores", "Av. Juárez 230, Col. Jardines",
          "Calle Roble 8, Col. Bosques", "Privada Sauce 3, Col. Arboledas"]


def _admin(conn) -> dict:
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT u.id, u.usuario FROM usuarios u JOIN roles r ON r.id = u.rol_id "
                "WHERE r.nombre = 'administrador' AND u.activo = 1 ORDER BY u.id LIMIT 1")
    fila = cur.fetchone()
    cur.close()
    if not fila:
        raise SystemExit("No hay administrador. Ejecute primero: python -m oceanica.init_db")
    return {"id": fila["id"], "usuario": fila["usuario"], "rol": "administrador", "empleado_id": None}


def _contar(conn, tabla: str) -> int:
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {tabla}")
    n = cur.fetchone()[0]
    cur.close()
    return n


def _catalogo(conn, adm) -> list[dict]:
    cats = {c["nombre"]: c["id"] for c in catalogo.listar_categorias(conn)}
    existentes = {s["nombre"] for s in catalogo.listar_servicios(conn, solo_activos=False)}
    for cat, servicios in SERVICIOS.items():
        if cat not in cats:
            cats[cat] = catalogo.crear_categoria(conn, adm, cat)
        for nombre, unidad, precio in servicios:
            if nombre not in existentes:
                catalogo.crear_servicio(conn, adm, cats[cat], nombre, unidad, precio)
    return catalogo.listar_servicios(conn)


def _empleados(conn, adm) -> list[str]:
    hechos = []
    presentes = {f["nombre"] for f in usuarios.listar_para_pin(conn)}
    for nombre, apellidos, pin, puesto in EMPLEADOS:
        if f"{nombre} {apellidos}" in presentes:
            continue
        usuarios.alta_empleado_con_acceso(conn, adm, nombre, apellidos, date.today() - timedelta(days=400), pin,
                                          f"55{random.randint(10000000, 99999999)}", puesto)
        hechos.append(f"{nombre} {apellidos}: PIN {pin}")
    return hechos


def _insumos(conn, adm):
    if inventario.listar_insumos(conn):
        return
    cats = {c["nombre"]: c["id"] for c in inventario.listar_categorias(conn)}
    prov = inventario.crear_proveedor(conn, adm, "Distribuidora Limpia", "Sr. Ramos", "5550001122")
    primera = next(iter(cats.values()))
    for cat, nombre, unidad, minimo, costo, existencia in [
            ("Detergentes y suavizantes", "Detergente líquido", "litro", 20, 38, 45),
            ("Detergentes y suavizantes", "Suavizante", "litro", 15, 32, 8),
            ("Detergentes y suavizantes", "Blanqueador", "litro", 10, 25, 14),
            ("Empaque y bolsas", "Bolsa grande", "pieza", 200, 1.5, 120),
            ("Ganchos y etiquetas", "Gancho de plástico", "pieza", 150, 2, 400)]:
        inventario.crear_insumo(conn, adm, cats.get(cat, primera), nombre, unidad, minimo, costo, prov, existencia)


def generar(conn, dias: int = 365, semilla: int = 7) -> dict:
    random.seed(semilla)
    adm = _admin(conn)
    servicios = _catalogo(conn, adm)
    pines = _empleados(conn, adm)
    _insumos(conn, adm)
    ids = [clientes.crear_cliente(conn, adm, n, a, f"55{random.randint(10000000, 99999999)}") for n, a in CLIENTES]
    pesos = [12, 9, 8, 7, 6, 5, 5, 4] + [2] * (len(ids) - 8)
    if configuracion.obtener(conn, "cargo_domicilio", "0") in ("", "0", "0.00"):
        configuracion.establecer(conn, adm, "cargo_domicilio", "40")
    kilo = [s for s in servicios if s["unidad"] == "kilo"]
    piezas = [s for s in servicios if s["unidad"] == "pieza"]
    metodos = caja.listar_metodos(conn)
    peso_metodo = [6 if m["es_efectivo"] else (3 if m["requiere_confirmacion"] else 1) for m in metodos]
    empleados = [u["usuario_id"] for u in usuarios.listar_para_pin(conn)] or [adm["id"]]

    if caja.corte_abierto(conn):
        raise SystemExit("Hay una caja abierta. Ciérrela antes de generar los datos de ejemplo.")
    inicio = datetime.now().replace(hour=8, minute=30, second=0, microsecond=0) - timedelta(days=dias)
    corte = caja.abrir_corte(conn, adm, 500)
    cur = conn.cursor()
    cur.execute("UPDATE cortes_caja SET abierta_en = %s WHERE id = %s", (inicio, corte))
    conn.commit()

    def items_al_azar():
        it = [{"servicio_id": kilo[0]["id"], "cantidad": D(random.choice([2.5, 3, 4, 4.5, 5, 6, 7, 8]))}] if kilo else []
        if piezas and (not it or random.random() < 0.45):
            for s in random.sample(piezas, random.choice([1, 1, 2])):
                it.append({"servicio_id": s["id"], "cantidad": random.randint(1, 3)})
        return it

    total_ordenes = 0
    hoy = datetime.now()
    for d in range(dias, 0, -1):  # días anteriores: órdenes ya entregadas y pagadas
        dia = hoy - timedelta(days=d)
        if dia.weekday() == 6 and random.random() < 0.8:  # casi siempre cerrado en domingo
            continue
        temporada = 1.4 if dia.month in (4, 11, 12) else 1.0
        crecimiento = 0.7 + 0.6 * (dias - d) / dias
        for _ in range(int(random.randint(2, 6) * temporada * crecimiento)):
            cli = random.choices(ids + [None], weights=pesos + [10])[0]
            domicilio = cli is not None and random.random() < 0.12
            entrega = {"tipo": "domicilio", "direccion": random.choice(CALLES)} if domicilio else None
            oid = ordenes.crear_orden(conn, adm, items_al_azar(), cli, None, 0, None, None, entrega)
            total = ordenes.obtener_orden(conn, oid)["total"]
            m = random.choices(metodos, weights=peso_metodo)[0]
            caja.registrar_pago(conn, adm, oid, m["id"], total, "pago",
                                f"DEMO{oid:06d}" if m["requiere_confirmacion"] else None)
            recibida = dia.replace(hour=random.randint(9, 18), minute=random.randint(0, 59))
            entregada = recibida + timedelta(days=random.choice([1, 2, 2, 3]))
            quien = random.choice(empleados)
            cur.execute("UPDATE ordenes SET fecha_recepcion=%s, fecha_promesa=%s, fecha_entrega=%s, estado='entregada', "
                        "usuario_id=%s WHERE id=%s", (recibida, recibida + timedelta(days=2), entregada, quien, oid))
            cur.execute("UPDATE orden_historial_estado SET cambiado_en=%s, usuario_id=%s WHERE orden_id=%s",
                        (recibida, quien, oid))
            cur.execute("INSERT INTO orden_historial_estado (orden_id, estado_anterior, estado_nuevo, usuario_id, "
                        "cambiado_en) VALUES (%s,'recibida','entregada',%s,%s)", (oid, quien, entregada))
            # MySQL asigna de izquierda a derecha: primero quién confirmó, al final el estado
            cur.execute("UPDATE pagos SET pagado_en=%s, usuario_id=%s, "
                        "confirmado_por=IF(estado_confirmacion='pendiente', %s, confirmado_por), "
                        "confirmado_en=IF(estado_confirmacion='pendiente', %s, confirmado_en), "
                        "estado_confirmacion='confirmado' WHERE orden_id=%s",
                        (entregada, quien, adm["id"], entregada, oid))
            total_ordenes += 1
        conn.commit()
        if d % 30 == 0:
            print(f"  … {MESES_LARGOS[dia.month - 1]} {dia.year}: {total_ordenes} órdenes", flush=True)

    # cerrar la caja de ejemplo sin diferencia
    esperado = caja.resumen_corte(conn, corte)["efectivo_esperado"]
    caja.cerrar_corte(conn, adm, esperado)
    cur.execute("UPDATE cortes_caja SET cerrada_en=%s WHERE id=%s", (hoy - timedelta(days=1), corte))
    conn.commit()

    # órdenes abiertas de hoy y ayer, en varios estados, para probar el mostrador y «Órdenes»
    abiertas = []
    for estado, dias_atras, pago in [("recibida", 0, None), ("recibida", 0, "anticipo"), ("en_proceso", 1, None),
                                     ("en_proceso", 1, "anticipo"), ("lista", 2, None), ("lista", 2, "todo"),
                                     ("lista", 4, None), ("recibida", 0, "transferencia")]:
        cli = random.choice(ids)
        entrega = {"tipo": "domicilio", "direccion": random.choice(CALLES)} if len(abiertas) == 3 else None
        oid = ordenes.crear_orden(conn, adm, items_al_azar(), cli, None, 0,
                                  "Revisar mancha en la manga" if len(abiertas) == 1 else None, None, entrega)
        abiertas.append((oid, estado, dias_atras, pago))
    corte_hoy = caja.abrir_corte(conn, adm, 500)
    ef = next(m for m in metodos if m["es_efectivo"])
    tr = next((m for m in metodos if m["requiere_confirmacion"]), ef)
    for oid, estado, dias_atras, pago in abiertas:
        total = ordenes.obtener_orden(conn, oid)["total"]
        if pago == "anticipo":
            caja.registrar_pago(conn, adm, oid, ef["id"], (total / 2).quantize(D("1")), "anticipo")
        elif pago == "todo":
            caja.registrar_pago(conn, adm, oid, ef["id"], total, "pago")
        elif pago == "transferencia":
            caja.registrar_pago(conn, adm, oid, tr["id"], total, "anticipo", "CAPTURA DE PANTALLA")
        recibida = hoy - timedelta(days=dias_atras, hours=random.randint(1, 4))
        cur.execute("UPDATE ordenes SET fecha_recepcion=%s, fecha_promesa=%s, estado=%s WHERE id=%s",
                    (recibida, recibida + timedelta(days=2 if dias_atras < 4 else 1), estado, oid))
    conn.commit()
    caja.cerrar_corte(conn, adm, caja.resumen_corte(conn, corte_hoy)["efectivo_esperado"])
    cur.close()
    return {"ordenes": total_ordenes + len(abiertas), "clientes": len(ids), "servicios": len(servicios), "pines": pines}


def main() -> int:
    cfg = cargar_config()
    print("== Datos de ejemplo para probar Oceánica ==")
    print(f"Base: {cfg.base} en {cfg.host}")
    print("ATENCIÓN: esto es solo para pruebas. NUNCA lo ejecute en la computadora de la lavandería.")
    conn = conectar(cfg)
    aplicar_migraciones(conn)
    if _contar(conn, "ordenes") and "--forzar" not in sys.argv:
        print("La base ya tiene órdenes, así que no se agregó nada (para no mezclar datos).")
        print("Si de verdad es una base de prueba, ejecute: python -m oceanica.datos_demo --forzar")
        return 1
    if "--si" not in sys.argv and input("Escriba SI para continuar: ").strip().upper() != "SI":
        print("Cancelado.")
        return 1
    print("Generando… (puede tardar uno o dos minutos)")
    r = generar(conn)
    conn.close()
    print(f"\nListo: {r['ordenes']} órdenes, {r['clientes']} clientes y {r['servicios']} servicios.")
    if r["pines"]:
        print("Empleados de prueba para el mostrador:")
        for p in r["pines"]:
            print("  ", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
