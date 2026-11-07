"""Nómina como control interno de pagos (sin cálculo fiscal: ISR, IMSS, CFDI).

Cómo se calcula un periodo (ver README para ejemplos):
  * Esquema 'hora':   sueldo = horas trabajadas x monto.
  * Esquema 'dia':    sueldo = días pagados x monto.
  * Esquema 'semana' / 'quincena': monto fijo del periodo (prorrateado si el empleado entró o salió a mitad
    del periodo, o si el esquema no coincide con la periodicidad); cada falta descuenta 1/7 (semana) o 1/15
    (quincena) del monto.
  * Días pagados = presentes + retardos (+ justificadas si 'asistencia_paga_justificada' = si).
  * Hora extra = horas extra de asistencia x valor de la hora x factor de configuración.
  * Bonos, descuentos, retardos y otros conceptos se capturan manualmente y sobreviven a un recálculo.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from ..db import transaccion
from .caja import registrar_movimiento_cur
from .empleados import _turno_del_dia
from .comunes import (CERO, ErrorNegocio, auditar, como_fecha, config_si, config_valor, dinero, requerir_rol,
                      texto)

ESQUEMAS = ("hora", "dia", "semana", "quincena")
_DIAS_ESQUEMA = {"semana": 7, "quincena": 15}
_COINCIDE = {("semana", "semanal"), ("quincena", "quincenal")}


# ---------- Salarios --------------------------------------------------------

def fijar_salario(conn, sesion, empleado_id: int, esquema: str, monto, vigente_desde) -> int:
    requerir_rol(sesion, "administrador")
    if esquema not in ESQUEMAS:
        raise ErrorNegocio("El esquema debe ser hora, dia, semana o quincena.")
    monto = dinero(monto, "sueldo")
    if monto <= 0:
        raise ErrorNegocio("El sueldo debe ser mayor que cero.")
    desde = como_fecha(vigente_desde, "vigente desde")
    with transaccion(conn) as cur:
        cur.execute("SELECT id FROM empleados WHERE id = %s FOR UPDATE", (empleado_id,))
        if not cur.fetchone():
            raise ErrorNegocio("Empleado no encontrado.")
        cur.execute("SELECT COUNT(*) AS n FROM historial_salarios WHERE empleado_id = %s AND vigente_desde >= %s",
                    (empleado_id, desde))
        if cur.fetchone()["n"]:
            raise ErrorNegocio("Ya existe un sueldo registrado con esa fecha o posterior.")
        cur.execute("SELECT esquema, monto FROM historial_salarios WHERE empleado_id = %s AND vigente_hasta IS NULL",
                    (empleado_id,))
        previo = cur.fetchone()
        cur.execute("UPDATE historial_salarios SET vigente_hasta = %s WHERE empleado_id = %s AND vigente_hasta IS NULL",
                    (desde - timedelta(days=1), empleado_id))
        cur.execute(
            "INSERT INTO historial_salarios (empleado_id, esquema, monto, vigente_desde, registrado_por) "
            "VALUES (%s,%s,%s,%s,%s)", (empleado_id, esquema, monto, desde, sesion["id"]))
        nuevo = cur.lastrowid
        anterior = f"{previo['esquema']} ${previo['monto']}" if previo else "sin sueldo previo"
        auditar(cur, sesion, "salario_cambiado", "historial_salarios", nuevo,
                f"empleado {empleado_id}: {anterior} -> {esquema} ${monto} desde {desde}")
        return nuevo


def historial_salarios(conn, sesion, empleado_id: int) -> list[dict]:
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        cur.execute(
            "SELECT h.*, u.usuario AS registrado_por_usuario FROM historial_salarios h "
            "JOIN usuarios u ON u.id = h.registrado_por WHERE h.empleado_id = %s ORDER BY h.vigente_desde DESC",
            (empleado_id,))
        return cur.fetchall()


def _salario_en(cur, empleado_id: int, fecha: date):
    cur.execute(
        "SELECT esquema, monto FROM historial_salarios WHERE empleado_id = %s AND vigente_desde <= %s "
        "AND (vigente_hasta IS NULL OR vigente_hasta >= %s) ORDER BY vigente_desde DESC LIMIT 1",
        (empleado_id, fecha, fecha))
    return cur.fetchone()


# ---------- Periodos --------------------------------------------------------

def abrir_periodo(conn, sesion, periodicidad: str, fecha_inicio, fecha_fin) -> int:
    requerir_rol(sesion, "administrador")
    if periodicidad not in ("semanal", "quincenal"):
        raise ErrorNegocio("La periodicidad debe ser semanal o quincenal.")
    ini, fin = como_fecha(fecha_inicio, "inicio"), como_fecha(fecha_fin, "fin")
    if fin < ini:
        raise ErrorNegocio("La fecha final no puede ser anterior a la inicial.")
    dias = (fin - ini).days + 1
    if periodicidad == "semanal" and dias != 7:
        raise ErrorNegocio("Un periodo semanal debe durar 7 días.")
    if periodicidad == "quincenal" and not 14 <= dias <= 16:
        raise ErrorNegocio("Un periodo quincenal debe durar entre 14 y 16 días.")
    with transaccion(conn) as cur:
        cur.execute("SELECT id FROM periodos_nomina WHERE periodicidad = %s AND fecha_inicio <= %s AND fecha_fin >= %s",
                    (periodicidad, fin, ini))
        if cur.fetchone():
            raise ErrorNegocio("Ese periodo se traslapa con otro ya existente.")
        cur.execute("INSERT INTO periodos_nomina (periodicidad, fecha_inicio, fecha_fin) VALUES (%s,%s,%s)",
                    (periodicidad, ini, fin))
        nuevo = cur.lastrowid
        auditar(cur, sesion, "periodo_abierto", "periodos_nomina", nuevo, f"{periodicidad} {ini} a {fin}")
        return nuevo


def _periodo(cur, periodo_id: int, estado_requerido: str | None = None) -> dict:
    cur.execute("SELECT * FROM periodos_nomina WHERE id = %s FOR UPDATE", (periodo_id,))
    p = cur.fetchone()
    if not p:
        raise ErrorNegocio("Periodo no encontrado.")
    if estado_requerido and p["estado"] != estado_requerido:
        raise ErrorNegocio(f"El periodo está '{p['estado']}'; se requiere que esté '{estado_requerido}'.")
    return p


def _recalcular_totales(cur, nomina_id: int) -> dict:
    cur.execute(
        "SELECT c.tipo, COALESCE(SUM(d.monto), 0) AS total FROM nomina_detalle d "
        "JOIN conceptos_nomina c ON c.id = d.concepto_id WHERE d.nomina_empleado_id = %s GROUP BY c.tipo", (nomina_id,))
    t = {f["tipo"]: Decimal(f["total"]) for f in cur.fetchall()}
    perc, ded = t.get("percepcion", CERO), t.get("deduccion", CERO)
    cur.execute("UPDATE nomina_empleado SET total_percepciones=%s, total_deducciones=%s, neto=%s WHERE id=%s",
                (perc, ded, perc - ded, nomina_id))
    return {"percepciones": perc, "deducciones": ded, "neto": perc - ded}


def _agregar_linea(cur, nomina_id, conceptos, clave, descripcion, monto, automatico):
    cur.execute(
        "INSERT INTO nomina_detalle (nomina_empleado_id, concepto_id, descripcion, monto, automatico) "
        "VALUES (%s,%s,%s,%s,%s)", (nomina_id, conceptos[clave], descripcion, monto, int(automatico)))


def calcular_periodo(conn, sesion, periodo_id: int) -> dict:
    """Calcula (o recalcula) la nómina de todos los empleados del periodo.
    Devuelve {'empleados': n, 'advertencias': [...]}: revisa las advertencias antes de aprobar."""
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        p = _periodo(cur, periodo_id, "abierto")
        ini, fin = p["fecha_inicio"], p["fecha_fin"]
        dias_periodo = (fin - ini).days + 1
        jornada = Decimal(config_valor(cur, "nomina_jornada_horas", "8") or "8")
        factor = Decimal(config_valor(cur, "nomina_factor_hora_extra", "2") or "2")
        paga_just = config_si(cur, "asistencia_paga_justificada", True)
        cur.execute("SELECT id, clave FROM conceptos_nomina")
        conceptos = {f["clave"]: f["id"] for f in cur.fetchall()}
        cur.execute(
            "SELECT * FROM empleados WHERE fecha_ingreso <= %s AND (fecha_baja IS NULL OR fecha_baja >= %s) "
            "ORDER BY apellidos, nombre", (fin, ini))
        empleados = cur.fetchall()
        advertencias, procesados = [], 0

        for e in empleados:
            nombre = f"{e['nombre']} {e['apellidos']}"
            ultimo_dia = min(fin, e["fecha_baja"]) if e["fecha_baja"] else fin
            primer_dia = max(ini, e["fecha_ingreso"])
            dias_activos = (ultimo_dia - primer_dia).days + 1
            sal = _salario_en(cur, e["id"], ultimo_dia)
            if not sal:
                advertencias.append(f"{nombre}: no tiene sueldo registrado, se omitió.")
                continue
            monto, esquema = Decimal(sal["monto"]), sal["esquema"]

            cur.execute(
                "SELECT estado, COUNT(*) AS n, COALESCE(SUM(horas_extra),0) AS hx, "
                "COALESCE(SUM(TIMESTAMPDIFF(MINUTE, hora_entrada, hora_salida)),0) AS mins "
                "FROM asistencias WHERE empleado_id = %s AND fecha BETWEEN %s AND %s GROUP BY estado",
                (e["id"], ini, fin))
            por_estado = {f["estado"]: f for f in cur.fetchall()}
            n = lambda est: int(por_estado[est]["n"]) if est in por_estado else 0  # noqa: E731
            advertencias += _dias_sin_registro(cur, e["id"], nombre, primer_dia, ultimo_dia)
            dias_pagados = n("presente") + n("retardo") + (n("justificada") if paga_just else 0)
            horas_trab = dinero(sum(Decimal(f["mins"]) for f in por_estado.values()) / 60)
            horas_extra = sum((Decimal(f["hx"]) for f in por_estado.values()), CERO)
            faltas = n("falta")

            descuento_faltas = CERO
            if esquema == "hora":
                base, valor_hora = dinero(horas_trab * monto), monto
            elif esquema == "dia":
                base, valor_hora = dinero(dias_pagados * monto), monto / jornada
            else:
                dias_esq = _DIAS_ESQUEMA[esquema]
                coincide = (esquema, p["periodicidad"]) in _COINCIDE
                proporcion = Decimal(1) if coincide else Decimal(dias_periodo) / dias_esq
                base = dinero(monto * proporcion * Decimal(dias_activos) / Decimal(dias_periodo))
                valor_dia = monto / dias_esq
                descuento_faltas = min(base, dinero(valor_dia * faltas))
                valor_hora = valor_dia / jornada
            pago_hora_fija = Decimal(config_valor(cur, "nomina_pago_hora_extra", "0") or "0")
            pago_extra = dinero(horas_extra * (pago_hora_fija if pago_hora_fija > 0 else valor_hora * factor))

            cur.execute("SELECT id FROM nomina_empleado WHERE periodo_id = %s AND empleado_id = %s FOR UPDATE",
                        (periodo_id, e["id"]))
            fila = cur.fetchone()
            if fila:
                nom_id = fila["id"]
                cur.execute("UPDATE nomina_empleado SET dias_trabajados=%s, horas_trabajadas=%s WHERE id=%s",
                            (dias_pagados, horas_trab, nom_id))
                cur.execute("DELETE FROM nomina_detalle WHERE nomina_empleado_id = %s AND automatico = 1", (nom_id,))
            else:
                cur.execute("INSERT INTO nomina_empleado (periodo_id, empleado_id, dias_trabajados, horas_trabajadas) "
                            "VALUES (%s,%s,%s,%s)", (periodo_id, e["id"], dias_pagados, horas_trab))
                nom_id = cur.lastrowid
            if base > 0:
                _agregar_linea(cur, nom_id, conceptos, "SUELDO", f"Sueldo base ({esquema} ${monto})", base, True)
            if pago_extra > 0:
                _agregar_linea(cur, nom_id, conceptos, "HEXTRA", f"{horas_extra} h extra", pago_extra, True)
            if descuento_faltas > 0:
                _agregar_linea(cur, nom_id, conceptos, "FALTA", f"{faltas} falta(s)", descuento_faltas, True)
            _recalcular_totales(cur, nom_id)
            procesados += 1
        auditar(cur, sesion, "periodo_calculado", "periodos_nomina", periodo_id, f"{procesados} empleados")
        return {"empleados": procesados, "advertencias": advertencias}


def hoy() -> date:
    return date.today()


def _dias_sin_registro(cur, empleado_id: int, nombre: str, desde: date, hasta: date) -> list[str]:
    """Días con turno que ya pasaron y no tienen asistencia: probablemente se olvidó registrar la llegada.
    Los días de descanso (sin turno) no generan aviso, porque cada empleado descansa un día distinto."""
    hasta = min(hasta, hoy() - timedelta(days=1))
    if hasta < desde:
        return []
    cur.execute("SELECT fecha FROM asistencias WHERE empleado_id = %s AND fecha BETWEEN %s AND %s",
                (empleado_id, desde, hasta))
    registrados = {f["fecha"] for f in cur.fetchall()}
    cur.execute("SELECT COUNT(*) AS n FROM turnos WHERE empleado_id = %s", (empleado_id,))
    if not cur.fetchone()["n"]:
        return [f"{nombre}: no tiene horario definido, no se puede revisar su asistencia."]
    faltan = []
    dia = desde
    while dia <= hasta:
        if dia not in registrados and _turno_del_dia(cur, empleado_id, dia):
            faltan.append(dia.strftime("%d/%m"))
        dia += timedelta(days=1)
    if faltan:
        return [f"{nombre}: sin registro en días de trabajo ({', '.join(faltan)}). No se pagan; si sí vino, corrígelo en Asistencia."]
    return []


def semana_de(fecha: date) -> tuple[date, date]:
    """Lunes y domingo de la semana de `fecha`."""
    lunes = fecha - timedelta(days=fecha.weekday())
    return lunes, lunes + timedelta(days=6)


def crear_periodo_semanal(conn, sesion, fecha: date | None = None) -> int:
    """Abre el periodo semanal (lunes a domingo) que contiene `fecha`; si ya existe, devuelve ese."""
    requerir_rol(sesion, "administrador")
    ini, fin = semana_de(como_fecha(fecha, "fecha") if fecha else date.today())
    with transaccion(conn) as cur:
        cur.execute("SELECT id FROM periodos_nomina WHERE periodicidad = 'semanal' AND fecha_inicio = %s", (ini,))
        existente = cur.fetchone()
    return existente["id"] if existente else abrir_periodo(conn, sesion, "semanal", ini, fin)


def aplicar_salario_minimo(conn, sesion, vigente_desde=None) -> int:
    """Da de alta el sueldo (por día, salario mínimo configurado) a los empleados activos que no tienen ninguno."""
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        minimo = Decimal(config_valor(cur, "nomina_salario_minimo_diario", "0") or "0")
        cur.execute("SELECT e.id, e.fecha_ingreso FROM empleados e WHERE e.activo = 1 AND NOT EXISTS "
                    "(SELECT 1 FROM historial_salarios h WHERE h.empleado_id = e.id)")
        sin_sueldo = cur.fetchall()
    if minimo <= 0:
        raise ErrorNegocio("Configura primero el salario mínimo diario.")
    for e in sin_sueldo:
        fijar_salario(conn, sesion, e["id"], "dia", minimo, vigente_desde or e["fecha_ingreso"])
    return len(sin_sueldo)


def agregar_concepto(conn, sesion, nomina_empleado_id: int, clave: str, monto, descripcion: str) -> dict:
    """Agrega un bono, descuento u otro concepto manual a la nómina de un empleado."""
    requerir_rol(sesion, "administrador")
    monto = dinero(monto, "monto")
    if monto <= 0:
        raise ErrorNegocio("El monto debe ser mayor que cero.")
    descripcion = texto(descripcion, "descripción", 120)
    with transaccion(conn) as cur:
        cur.execute("SELECT periodo_id FROM nomina_empleado WHERE id = %s FOR UPDATE", (nomina_empleado_id,))
        n = cur.fetchone()
        if not n:
            raise ErrorNegocio("Nómina de empleado no encontrada.")
        _periodo(cur, n["periodo_id"], "abierto")
        cur.execute("SELECT id, clave FROM conceptos_nomina")
        conceptos = {f["clave"]: f["id"] for f in cur.fetchall()}
        if clave not in conceptos or clave in ("SUELDO", "HEXTRA", "FALTA"):
            raise ErrorNegocio("Concepto no válido para captura manual (usa BONO, OTRAPERC, RETARDO o DESCMAN).")
        _agregar_linea(cur, nomina_empleado_id, conceptos, clave, descripcion, monto, False)
        totales = _recalcular_totales(cur, nomina_empleado_id)
        if totales["neto"] < 0:
            raise ErrorNegocio("Las deducciones no pueden superar las percepciones del periodo.")
        auditar(cur, sesion, "nomina_concepto_agregado", "nomina_empleado", nomina_empleado_id,
                f"{clave} ${monto}: {descripcion}")
        return totales


def quitar_concepto(conn, sesion, detalle_id: int) -> dict:
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        cur.execute("SELECT d.nomina_empleado_id, d.automatico, n.periodo_id FROM nomina_detalle d "
                    "JOIN nomina_empleado n ON n.id = d.nomina_empleado_id WHERE d.id = %s FOR UPDATE", (detalle_id,))
        d = cur.fetchone()
        if not d:
            raise ErrorNegocio("Concepto no encontrado.")
        _periodo(cur, d["periodo_id"], "abierto")
        if d["automatico"]:
            raise ErrorNegocio("Los conceptos calculados por el sistema no se borran; corrige la asistencia y recalcula.")
        cur.execute("DELETE FROM nomina_detalle WHERE id = %s", (detalle_id,))
        totales = _recalcular_totales(cur, d["nomina_empleado_id"])
        auditar(cur, sesion, "nomina_concepto_quitado", "nomina_detalle", detalle_id)
        return totales


def aprobar_periodo(conn, sesion, periodo_id: int) -> None:
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        _periodo(cur, periodo_id, "abierto")
        cur.execute("SELECT COUNT(*) AS n, COALESCE(SUM(neto < 0), 0) AS negativos FROM nomina_empleado WHERE periodo_id = %s",
                    (periodo_id,))
        r = cur.fetchone()
        if r["n"] == 0:
            raise ErrorNegocio("Calcula la nómina antes de aprobarla.")
        if r["negativos"]:
            raise ErrorNegocio("Hay nóminas con neto negativo; corrígelas antes de aprobar.")
        cur.execute("UPDATE periodos_nomina SET estado='aprobado', aprobado_por=%s WHERE id=%s", (sesion["id"], periodo_id))
        auditar(cur, sesion, "periodo_aprobado", "periodos_nomina", periodo_id)


def reabrir_periodo(conn, sesion, periodo_id: int) -> None:
    """Regresa un periodo aprobado a 'abierto' para corregirlo, mientras no se haya pagado a nadie."""
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        _periodo(cur, periodo_id, "aprobado")
        cur.execute("SELECT COUNT(*) AS n FROM nomina_empleado WHERE periodo_id = %s AND pagado_en IS NOT NULL",
                    (periodo_id,))
        if cur.fetchone()["n"]:
            raise ErrorNegocio("Ya hay pagos registrados en este periodo; no se puede reabrir.")
        cur.execute("UPDATE periodos_nomina SET estado='abierto', aprobado_por=NULL WHERE id=%s", (periodo_id,))
        auditar(cur, sesion, "periodo_reabierto", "periodos_nomina", periodo_id)


def registrar_pago_empleado(conn, sesion, nomina_empleado_id: int, en_caja: bool = False,
                            metodo: str = "efectivo", recibo_firmado: bool = False) -> None:
    """Marca como pagada la nómina de un empleado.
    metodo 'efectivo': si en_caja, el pago sale de la caja como gasto del corte abierto.
    metodo 'transferencia': no mueve la caja (se paga desde la cuenta bancaria)."""
    requerir_rol(sesion, "administrador")
    if metodo not in ("efectivo", "transferencia"):
        raise ErrorNegocio("El método de pago debe ser efectivo o transferencia.")
    with transaccion(conn) as cur:
        cur.execute(
            "SELECT n.*, CONCAT_WS(' ', e.nombre, e.apellidos) AS empleado FROM nomina_empleado n "
            "JOIN empleados e ON e.id = n.empleado_id WHERE n.id = %s FOR UPDATE", (nomina_empleado_id,))
        n = cur.fetchone()
        if not n:
            raise ErrorNegocio("Nómina de empleado no encontrada.")
        p = _periodo(cur, n["periodo_id"], "aprobado")
        if n["pagado_en"]:
            raise ErrorNegocio("Esta nómina ya está marcada como pagada.")
        neto = Decimal(n["neto"])
        if neto <= 0:
            raise ErrorNegocio("No hay monto que pagar.")
        if en_caja and metodo == "efectivo":
            registrar_movimiento_cur(cur, sesion, "gasto",
                                     f"Nómina {n['empleado']} ({p['fecha_inicio']} a {p['fecha_fin']})", neto)
        cur.execute("UPDATE nomina_empleado SET pagado_en = NOW(), metodo_pago = %s, recibo_firmado = %s WHERE id = %s",
                    (metodo, int(bool(recibo_firmado)), nomina_empleado_id))
        auditar(cur, sesion, "nomina_pagada", "nomina_empleado", nomina_empleado_id, f"${neto} {metodo}")


def marcar_recibo_firmado(conn, sesion, nomina_empleado_id: int, firmado: bool = True) -> None:
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        cur.execute("UPDATE nomina_empleado SET recibo_firmado = %s WHERE id = %s", (int(bool(firmado)), nomina_empleado_id))
        if cur.rowcount == 0:
            cur.execute("SELECT id FROM nomina_empleado WHERE id = %s", (nomina_empleado_id,))
            if not cur.fetchone():
                raise ErrorNegocio("Nómina de empleado no encontrada.")
        auditar(cur, sesion, "recibo_firmado" if firmado else "recibo_sin_firma", "nomina_empleado", nomina_empleado_id)


def cerrar_periodo(conn, sesion, periodo_id: int) -> None:
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        _periodo(cur, periodo_id, "aprobado")
        cur.execute("SELECT COUNT(*) AS n FROM nomina_empleado WHERE periodo_id = %s AND pagado_en IS NULL AND neto > 0",
                    (periodo_id,))  # quien no trabajó (neto $0) no tiene nada que pagar
        pendientes = cur.fetchone()["n"]
        if pendientes:
            raise ErrorNegocio(f"Faltan {pendientes} nómina(s) por marcar como pagadas.")
        cur.execute("UPDATE periodos_nomina SET estado='cerrado', cerrado_en=NOW() WHERE id=%s", (periodo_id,))
        auditar(cur, sesion, "periodo_cerrado", "periodos_nomina", periodo_id)


# ---------- Consultas -------------------------------------------------------

def listar_periodos(conn, sesion, limite: int = 50) -> list[dict]:
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        cur.execute("SELECT * FROM periodos_nomina ORDER BY fecha_inicio DESC LIMIT %s", (int(limite),))
        return cur.fetchall()


def obtener_periodo(conn, sesion, periodo_id: int) -> dict:
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        cur.execute("SELECT * FROM periodos_nomina WHERE id = %s", (periodo_id,))
        p = cur.fetchone()
        if not p:
            raise ErrorNegocio("Periodo no encontrado.")
        cur.execute(
            "SELECT n.*, CONCAT_WS(' ', e.nombre, e.apellidos) AS empleado, e.puesto FROM nomina_empleado n "
            "JOIN empleados e ON e.id = n.empleado_id WHERE n.periodo_id = %s ORDER BY e.apellidos, e.nombre",
            (periodo_id,))
        p["nominas"] = cur.fetchall()
        for n in p["nominas"]:
            cur.execute(
                "SELECT d.id, c.clave, c.nombre AS concepto, c.tipo, d.descripcion, d.monto, d.automatico "
                "FROM nomina_detalle d JOIN conceptos_nomina c ON c.id = d.concepto_id "
                "WHERE d.nomina_empleado_id = %s ORDER BY c.tipo DESC, d.id", (n["id"],))
            n["detalle"] = cur.fetchall()
        p["total_neto"] = sum((Decimal(n["neto"]) for n in p["nominas"]), CERO)
        return p


def datos_recibo(conn, sesion, nomina_empleado_id: int) -> dict:
    """Información completa para imprimir el recibo de pago interno de un empleado."""
    requerir_rol(sesion, "administrador")
    with transaccion(conn) as cur:
        cur.execute("SELECT periodo_id FROM nomina_empleado WHERE id = %s", (nomina_empleado_id,))
        f = cur.fetchone()
    if not f:
        raise ErrorNegocio("Nómina de empleado no encontrada.")
    periodo = obtener_periodo(conn, sesion, f["periodo_id"])
    nomina = next(n for n in periodo["nominas"] if n["id"] == nomina_empleado_id)
    return {"periodo": {k: periodo[k] for k in ("id", "periodicidad", "fecha_inicio", "fecha_fin", "estado")},
            "nomina": nomina}
