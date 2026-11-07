"""Empleados, turnos y asistencia."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from ..db import transaccion
from .comunes import (ErrorNegocio, auditar, como_fecha, config_si, config_valor, dinero, requerir_rol, texto)

ESTADOS_MARCADOS = ("falta", "justificada", "descanso")


# ---------- Empleados -------------------------------------------------------

def crear_empleado(conn, sesion, nombre, apellidos, fecha_ingreso, telefono=None, puesto=None) -> int:
    requerir_rol(sesion, "administrador")
    datos = (texto(nombre, "nombre", 80), texto(apellidos, "apellidos", 80), texto(telefono, "teléfono", 20, False),
             texto(puesto, "puesto", 60, False), como_fecha(fecha_ingreso, "fecha de ingreso"))
    with transaccion(conn) as cur:
        cur.execute(
            "INSERT INTO empleados (nombre, apellidos, telefono, puesto, fecha_ingreso) VALUES (%s,%s,%s,%s,%s)", datos
        )
        nuevo = cur.lastrowid
        auditar(cur, sesion, "empleado_creado", "empleados", nuevo, f"{datos[0]} {datos[1]}")
        return nuevo


def actualizar_empleado(conn, sesion, empleado_id: int, **cambios) -> None:
    requerir_rol(sesion, "administrador")
    limites = {"nombre": 80, "apellidos": 80, "telefono": 20, "puesto": 60}
    malos = set(cambios) - set(limites)
    if malos:
        raise ErrorNegocio(f"Campos no editables: {', '.join(sorted(malos))}")
    if not cambios:
        return
    valores = {c: texto(v, c, limites[c], c in ("nombre", "apellidos")) for c, v in cambios.items()}
    sets = ", ".join(f"{c} = %s" for c in valores)
    with transaccion(conn) as cur:
        cur.execute("SELECT id FROM empleados WHERE id = %s", (empleado_id,))
        if not cur.fetchone():
            raise ErrorNegocio("Empleado no encontrado.")
        cur.execute(f"UPDATE empleados SET {sets} WHERE id = %s", (*valores.values(), empleado_id))
        auditar(cur, sesion, "empleado_actualizado", "empleados", empleado_id, ", ".join(valores))


def dar_de_baja(conn, sesion, empleado_id: int, fecha_baja) -> None:
    """Da de baja al empleado (conserva su historial) y desactiva su usuario, si tiene."""
    requerir_rol(sesion, "administrador")
    fecha_baja = como_fecha(fecha_baja, "fecha de baja")
    with transaccion(conn) as cur:
        cur.execute("SELECT * FROM empleados WHERE id = %s FOR UPDATE", (empleado_id,))
        e = cur.fetchone()
        if not e:
            raise ErrorNegocio("Empleado no encontrado.")
        if not e["activo"]:
            raise ErrorNegocio("El empleado ya está dado de baja.")
        if fecha_baja < e["fecha_ingreso"]:
            raise ErrorNegocio("La fecha de baja no puede ser anterior a la de ingreso.")
        cur.execute(
            "SELECT u.id, u.activo, r.nombre AS rol FROM usuarios u JOIN roles r ON r.id = u.rol_id "
            "WHERE u.empleado_id = %s", (empleado_id,))
        for u in cur.fetchall():
            if u["id"] == sesion["id"]:
                raise ErrorNegocio("No puedes dar de baja al empleado ligado a tu propio usuario.")
            if u["rol"] == "administrador" and u["activo"]:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM usuarios u JOIN roles r ON r.id = u.rol_id "
                    "WHERE r.nombre = 'administrador' AND u.activo = 1")
                if cur.fetchone()["n"] <= 1:
                    raise ErrorNegocio("Debe quedar al menos un administrador activo.")
            cur.execute("UPDATE usuarios SET activo = 0 WHERE id = %s", (u["id"],))
        cur.execute("UPDATE empleados SET activo = 0, fecha_baja = %s WHERE id = %s", (fecha_baja, empleado_id))
        cur.execute("UPDATE turnos SET vigente_hasta = %s WHERE empleado_id = %s AND vigente_hasta IS NULL",
                    (fecha_baja, empleado_id))
        auditar(cur, sesion, "empleado_baja", "empleados", empleado_id, str(fecha_baja))


def listar_empleados(conn, solo_activos: bool = True) -> list[dict]:
    with transaccion(conn) as cur:
        cur.execute("SELECT * FROM empleados " + ("WHERE activo = 1 " if solo_activos else "")
                    + "ORDER BY apellidos, nombre")
        return cur.fetchall()


# ---------- Turnos ----------------------------------------------------------

def _hora(valor, campo: str) -> time:
    if isinstance(valor, time):
        return valor
    if isinstance(valor, timedelta):
        total = int(valor.total_seconds())
        return time(total // 3600 % 24, total % 3600 // 60)
    try:
        h, m = str(valor).strip().split(":")[:2]
        return time(int(h), int(m))
    except (ValueError, TypeError):
        raise ErrorNegocio(f"El campo '{campo}' debe tener formato HH:MM.")


def _horas_turno(entrada: time, salida: time) -> Decimal:
    ini = datetime.combine(date.today(), entrada)
    fin = datetime.combine(date.today(), salida)
    if fin <= ini:  # turno que cruza la medianoche
        fin += timedelta(days=1)
    return dinero((fin - ini).total_seconds() / 3600)


def definir_turnos(conn, sesion, empleado_id: int, turnos: list[tuple], vigente_desde) -> None:
    """turnos: [(dia 1=lunes..7=domingo, 'HH:MM' entrada, 'HH:MM' salida), ...].
    Reemplaza el horario semanal vigente a partir de la fecha dada; el anterior queda en el historial."""
    requerir_rol(sesion, "administrador")
    desde = como_fecha(vigente_desde, "vigente desde")
    if not turnos:
        raise ErrorNegocio("Indica al menos un turno.")
    nuevos, vistos = [], set()
    for dia, entrada, salida in turnos:
        if dia not in range(1, 8):
            raise ErrorNegocio("El día debe ir de 1 (lunes) a 7 (domingo).")
        if dia in vistos:
            raise ErrorNegocio("Hay dos turnos para el mismo día.")
        vistos.add(dia)
        e, s = _hora(entrada, "hora de entrada"), _hora(salida, "hora de salida")
        if e == s:
            raise ErrorNegocio("La entrada y la salida no pueden ser la misma hora.")
        nuevos.append((dia, e, s))
    with transaccion(conn) as cur:
        cur.execute("SELECT id FROM empleados WHERE id = %s AND activo = 1 FOR UPDATE", (empleado_id,))
        if not cur.fetchone():
            raise ErrorNegocio("Empleado no encontrado o dado de baja.")
        cur.execute("DELETE FROM turnos WHERE empleado_id = %s AND vigente_desde >= %s", (empleado_id, desde))
        cur.execute(
            "UPDATE turnos SET vigente_hasta = %s WHERE empleado_id = %s AND (vigente_hasta IS NULL OR vigente_hasta >= %s)",
            (desde - timedelta(days=1), empleado_id, desde),
        )
        for dia, e, s in nuevos:
            cur.execute(
                "INSERT INTO turnos (empleado_id, dia_semana, hora_entrada, hora_salida, vigente_desde) "
                "VALUES (%s,%s,%s,%s,%s)", (empleado_id, dia, e, s, desde))
        auditar(cur, sesion, "turnos_definidos", "empleados", empleado_id, f"{len(nuevos)} días desde {desde}")


def turnos_vigentes(conn, empleado_id: int, fecha=None) -> list[dict]:
    fecha = como_fecha(fecha, "fecha") if fecha else date.today()
    with transaccion(conn) as cur:
        cur.execute(
            "SELECT dia_semana, hora_entrada, hora_salida FROM turnos WHERE empleado_id = %s "
            "AND vigente_desde <= %s AND (vigente_hasta IS NULL OR vigente_hasta >= %s) ORDER BY dia_semana",
            (empleado_id, fecha, fecha),
        )
        filas = cur.fetchall()
    for f in filas:
        f["hora_entrada"], f["hora_salida"] = _hora(f["hora_entrada"], "e"), _hora(f["hora_salida"], "s")
    return filas


def _turno_del_dia(cur, empleado_id: int, fecha: date):
    cur.execute(
        "SELECT hora_entrada, hora_salida FROM turnos WHERE empleado_id = %s AND dia_semana = %s "
        "AND vigente_desde <= %s AND (vigente_hasta IS NULL OR vigente_hasta >= %s) "
        "ORDER BY vigente_desde DESC LIMIT 1",
        (empleado_id, fecha.isoweekday(), fecha, fecha),
    )
    t = cur.fetchone()
    return (_hora(t["hora_entrada"], "e"), _hora(t["hora_salida"], "s")) if t else None


# ---------- Asistencia ------------------------------------------------------

def _evaluar(cur, empleado_id: int, fecha: date, entrada: datetime, salida: datetime | None):
    """Devuelve (estado, minutos_retardo, horas_extra) según el turno del día."""
    turno = _turno_del_dia(cur, empleado_id, fecha)
    estado, retardo, extra = "presente", 0, Decimal("0.00")
    if turno:
        tolerancia = int(config_valor(cur, "hora_entrada_tolerancia_min", "10") or 0)
        tarde = int((entrada - datetime.combine(fecha, turno[0])).total_seconds() // 60)
        if tarde > tolerancia:
            estado, retardo = "retardo", tarde
        if salida:
            trabajadas = dinero((salida - entrada).total_seconds() / 3600)
            if config_si(cur, "horas_extra_automaticas", False):
                extra = max(Decimal("0.00"), trabajadas - _horas_turno(*turno))
    return estado, retardo, extra


def registrar_entrada(conn, sesion, empleado_id: int, ahora: datetime | None = None) -> dict:
    requerir_rol(sesion, "administrador", "empleado")
    ahora = (ahora or datetime.now()).replace(microsecond=0)
    fecha = ahora.date()
    with transaccion(conn) as cur:
        cur.execute("SELECT id FROM empleados WHERE id = %s AND activo = 1", (empleado_id,))
        if not cur.fetchone():
            raise ErrorNegocio("Empleado no encontrado o dado de baja.")
        cur.execute("SELECT id, hora_entrada, estado FROM asistencias WHERE empleado_id = %s AND fecha = %s FOR UPDATE",
                    (empleado_id, fecha))
        previa = cur.fetchone()
        if previa:
            raise ErrorNegocio("Ya hay una asistencia registrada hoy para este empleado.")
        estado, retardo, _ = _evaluar(cur, empleado_id, fecha, ahora, None)
        cur.execute(
            "INSERT INTO asistencias (empleado_id, fecha, hora_entrada, estado, minutos_retardo, registrado_por) "
            "VALUES (%s,%s,%s,%s,%s,%s)", (empleado_id, fecha, ahora, estado, retardo, sesion["id"]))
        auditar(cur, sesion, "asistencia_entrada", "asistencias", cur.lastrowid, f"empleado {empleado_id}")
        return {"estado": estado, "minutos_retardo": retardo, "hora_entrada": ahora}


def registrar_salida(conn, sesion, empleado_id: int, ahora: datetime | None = None) -> dict:
    requerir_rol(sesion, "administrador", "empleado")
    ahora = (ahora or datetime.now()).replace(microsecond=0)
    with transaccion(conn) as cur:
        cur.execute(
            "SELECT id, fecha, hora_entrada FROM asistencias WHERE empleado_id = %s AND hora_entrada IS NOT NULL "
            "AND hora_salida IS NULL AND fecha >= %s ORDER BY fecha DESC LIMIT 1 FOR UPDATE",
            (empleado_id, ahora.date() - timedelta(days=1)),
        )
        a = cur.fetchone()
        if not a:
            raise ErrorNegocio("No hay una entrada abierta para este empleado.")
        if ahora <= a["hora_entrada"]:
            raise ErrorNegocio("La salida debe ser posterior a la entrada.")
        _, _, extra = _evaluar(cur, empleado_id, a["fecha"], a["hora_entrada"], ahora)
        if config_si(cur, "horas_extra_automaticas", False):
            cur.execute("UPDATE asistencias SET hora_salida = %s, horas_extra = %s WHERE id = %s", (ahora, extra, a["id"]))
        else:  # las horas extra las autoriza la encargada (autorizar_horas_extra); aquí no se tocan
            cur.execute("UPDATE asistencias SET hora_salida = %s WHERE id = %s", (ahora, a["id"]))
            cur.execute("SELECT horas_extra FROM asistencias WHERE id = %s", (a["id"],))
            extra = cur.fetchone()["horas_extra"]
        auditar(cur, sesion, "asistencia_salida", "asistencias", a["id"], f"empleado {empleado_id}")
        horas = dinero((ahora - a["hora_entrada"]).total_seconds() / 3600)
        return {"hora_salida": ahora, "horas_trabajadas": horas, "horas_extra": extra}


def marcar_estado(conn, sesion, empleado_id: int, fecha, estado: str, observaciones: str | None = None) -> None:
    """Marca falta, falta justificada o descanso (solo administrador)."""
    requerir_rol(sesion, "administrador")
    fecha = como_fecha(fecha)
    if estado not in ESTADOS_MARCADOS:
        raise ErrorNegocio("El estado debe ser 'falta', 'justificada' o 'descanso'.")
    observaciones = texto(observaciones, "observaciones", 200, estado == "justificada")
    with transaccion(conn) as cur:
        cur.execute("SELECT id FROM empleados WHERE id = %s", (empleado_id,))
        if not cur.fetchone():
            raise ErrorNegocio("Empleado no encontrado.")
        cur.execute("SELECT id, hora_entrada FROM asistencias WHERE empleado_id = %s AND fecha = %s FOR UPDATE",
                    (empleado_id, fecha))
        a = cur.fetchone()
        if a and a["hora_entrada"]:
            raise ErrorNegocio("Ese día ya tiene entrada registrada. Usa corregir_asistencia.")
        if a:
            cur.execute("UPDATE asistencias SET estado=%s, observaciones=%s, registrado_por=%s WHERE id=%s",
                        (estado, observaciones, sesion["id"], a["id"]))
            reg = a["id"]
        else:
            cur.execute(
                "INSERT INTO asistencias (empleado_id, fecha, estado, observaciones, registrado_por) VALUES (%s,%s,%s,%s,%s)",
                (empleado_id, fecha, estado, observaciones, sesion["id"]))
            reg = cur.lastrowid
        auditar(cur, sesion, f"asistencia_{estado}", "asistencias", reg, f"empleado {empleado_id} {fecha}")


def corregir_asistencia(conn, sesion, empleado_id: int, fecha, hora_entrada: datetime,
                        hora_salida: datetime | None, motivo: str) -> dict:
    """Captura o corrige horas de un día (solo administrador, con motivo). Recalcula retardo y horas extra."""
    requerir_rol(sesion, "administrador")
    fecha = como_fecha(fecha)
    motivo = texto(motivo, "motivo", 200)
    if hora_salida is not None and hora_salida <= hora_entrada:
        raise ErrorNegocio("La salida debe ser posterior a la entrada.")
    with transaccion(conn) as cur:
        cur.execute("SELECT id FROM empleados WHERE id = %s", (empleado_id,))
        if not cur.fetchone():
            raise ErrorNegocio("Empleado no encontrado.")
        estado, retardo, extra = _evaluar(cur, empleado_id, fecha, hora_entrada, hora_salida)
        if not config_si(cur, "horas_extra_automaticas", False):  # conserva las horas extra ya autorizadas
            cur.execute("SELECT horas_extra FROM asistencias WHERE empleado_id = %s AND fecha = %s", (empleado_id, fecha))
            previa = cur.fetchone()
            extra = previa["horas_extra"] if previa else Decimal("0.00")
        cur.execute(
            "INSERT INTO asistencias (empleado_id, fecha, hora_entrada, hora_salida, estado, minutos_retardo, "
            "horas_extra, observaciones, registrado_por) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE hora_entrada=VALUES(hora_entrada), hora_salida=VALUES(hora_salida), "
            "estado=VALUES(estado), minutos_retardo=VALUES(minutos_retardo), horas_extra=VALUES(horas_extra), "
            "observaciones=VALUES(observaciones), registrado_por=VALUES(registrado_por)",
            (empleado_id, fecha, hora_entrada, hora_salida, estado, retardo, extra, motivo, sesion["id"]),
        )
        auditar(cur, sesion, "asistencia_corregida", "asistencias", None, f"empleado {empleado_id} {fecha}: {motivo}")
        return {"estado": estado, "minutos_retardo": retardo, "horas_extra": extra}


def autorizar_horas_extra(conn, sesion, empleado_id: int, fecha, horas, motivo: str) -> Decimal:
    """La encargada (administrador) autoriza las horas extra de un día ya trabajado. horas=0 las quita."""
    requerir_rol(sesion, "administrador")
    fecha = como_fecha(fecha)
    horas = dinero(horas, "horas")
    if not Decimal(0) <= horas <= Decimal(8):
        raise ErrorNegocio("Las horas extra deben estar entre 0 y 8.")
    motivo = texto(motivo, "motivo", 200)
    with transaccion(conn) as cur:
        cur.execute("SELECT id, estado FROM asistencias WHERE empleado_id = %s AND fecha = %s AND hora_entrada IS NOT NULL "
                    "FOR UPDATE", (empleado_id, fecha))
        a = cur.fetchone()
        if not a:
            raise ErrorNegocio("Ese empleado no tiene asistencia registrada ese día.")
        cur.execute("UPDATE asistencias SET horas_extra = %s, observaciones = %s WHERE id = %s", (horas, motivo, a["id"]))
        auditar(cur, sesion, "horas_extra_autorizadas", "asistencias", a["id"], f"empleado {empleado_id} {fecha}: {horas} h, {motivo}")
        return horas


def listar_asistencias(conn, desde, hasta, empleado_id: int | None = None) -> list[dict]:
    desde, hasta = como_fecha(desde, "desde"), como_fecha(hasta, "hasta")
    sql = ("SELECT a.*, CONCAT_WS(' ', e.nombre, e.apellidos) AS empleado FROM asistencias a "
           "JOIN empleados e ON e.id = a.empleado_id WHERE a.fecha BETWEEN %s AND %s")
    params: list = [desde, hasta]
    if empleado_id:
        sql += " AND a.empleado_id = %s"
        params.append(empleado_id)
    with transaccion(conn) as cur:
        cur.execute(sql + " ORDER BY a.fecha, e.apellidos, e.nombre", params)
        return cur.fetchall()
