"""Importación inicial desde CSV o Excel: servicios, insumos, empleados y clientes.

Todo o nada: si alguna fila tiene errores no se guarda nada y se devuelve la lista de errores
con el número de fila (la fila 1 es el encabezado). Los registros que ya existen se omiten.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ..db import transaccion
from .comunes import ErrorNegocio, auditar, dinero, requerir_rol

MAX_FILAS = 5000

PLANTILLAS: dict[str, list[str]] = {
    "servicios": ["categoria", "nombre", "unidad", "precio"],
    "insumos": ["categoria", "nombre", "unidad", "existencia", "minimo", "costo_unitario", "proveedor"],
    "empleados": ["nombre", "apellidos", "telefono", "puesto", "fecha_ingreso"],
    "clientes": ["nombre", "apellidos", "telefono", "email", "notas"],
}
_OBLIGATORIAS = {
    "servicios": {"categoria", "nombre", "unidad", "precio"},
    "insumos": {"categoria", "nombre"},
    "empleados": {"nombre", "apellidos", "fecha_ingreso"},
    "clientes": {"nombre"},
}
_ALIAS = {"fecha_de_ingreso": "fecha_ingreso", "costo": "costo_unitario", "telefono_celular": "telefono",
          "correo": "email", "correo_electronico": "email", "stock": "existencia", "cantidad": "existencia"}


def _norm(h) -> str:
    s = unicodedata.normalize("NFKD", str(h or "")).encode("ascii", "ignore").decode().lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return _ALIAS.get(s, s)


def generar_plantilla(tipo: str, ruta) -> Path:
    """Crea un CSV vacío con las columnas esperadas, listo para llenar en Excel."""
    if tipo not in PLANTILLAS:
        raise ErrorNegocio(f"Tipo desconocido. Opciones: {', '.join(PLANTILLAS)}")
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow(PLANTILLAS[tipo])
    return ruta


def _leer(ruta) -> list[dict]:
    ruta = Path(ruta)
    if not ruta.exists():
        raise ErrorNegocio("No se encontró el archivo.")
    if ruta.suffix.lower() in (".xlsx", ".xlsm"):
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ErrorNegocio("Para leer Excel instala openpyxl (pip install openpyxl) o guarda el archivo como CSV.")
        hoja = load_workbook(ruta, read_only=True, data_only=True).active
        filas = [list(r) for r in hoja.iter_rows(values_only=True)]
    elif ruta.suffix.lower() == ".csv":
        crudo = ruta.read_bytes()
        try:
            texto = crudo.decode("utf-8-sig")
        except UnicodeDecodeError:
            texto = crudo.decode("cp1252")  # CSV guardado desde Excel en Windows
        try:
            dialecto = csv.Sniffer().sniff(texto[:4096], delimiters=",;\t")
        except csv.Error:
            dialecto = csv.excel
        filas = list(csv.reader(texto.splitlines(), dialecto))
    else:
        raise ErrorNegocio("Formato no soportado: usa .csv o .xlsx")
    filas = [r for r in filas if any(str(c).strip() for c in r if c is not None)]
    if len(filas) < 2:
        raise ErrorNegocio("El archivo no tiene datos (solo encabezado o vacío).")
    if len(filas) - 1 > MAX_FILAS:
        raise ErrorNegocio(f"El archivo tiene demasiadas filas (máximo {MAX_FILAS}).")
    cab = [_norm(c) for c in filas[0]]
    return [{"_fila": i, **{c: (v if v is not None else "") for c, v in zip(cab, fila)}}
            for i, fila in enumerate(filas[1:], start=2)]


def _txt(v) -> str:
    return str(v).strip() if v is not None else ""


def _num(v, campo, defecto=None) -> Decimal:
    s = _txt(v).replace("$", "").replace(" ", "")
    if not s:
        if defecto is None:
            raise ValueError(f"'{campo}' está vacío")
        return defecto
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        d = dinero(s, campo)
    except ErrorNegocio:
        raise ValueError(f"'{campo}' no es un número válido ('{v}')")
    if d < 0:
        raise ValueError(f"'{campo}' no puede ser negativo")
    return d


def _fecha(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = _txt(v)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"fecha inválida '{v}' (usa AAAA-MM-DD o DD/MM/AAAA)")


def _largo(valor: str, campo: str, maximo: int, obligatorio=True) -> str | None:
    if not valor:
        if obligatorio:
            raise ValueError(f"'{campo}' está vacío")
        return None
    if len(valor) > maximo:
        raise ValueError(f"'{campo}' excede {maximo} caracteres")
    return valor


def _preparar(tipo: str, r: dict):
    t = _txt
    if tipo == "servicios":
        unidad = t(r.get("unidad")).lower()
        if unidad not in ("kilo", "pieza"):
            raise ValueError("'unidad' debe ser 'kilo' o 'pieza'")
        return (_largo(t(r.get("categoria")), "categoria", 60), _largo(t(r.get("nombre")), "nombre", 80),
                unidad, _num(r.get("precio"), "precio"))
    if tipo == "insumos":
        return (_largo(t(r.get("categoria")), "categoria", 60), _largo(t(r.get("nombre")), "nombre", 80),
                _largo(t(r.get("unidad")), "unidad", 15, False) or "pieza", _num(r.get("existencia"), "existencia", Decimal(0)),
                _num(r.get("minimo"), "minimo", Decimal(0)), _num(r.get("costo_unitario"), "costo_unitario", Decimal(0)),
                _largo(t(r.get("proveedor")), "proveedor", 100, False))
    if tipo == "empleados":
        return (_largo(t(r.get("nombre")), "nombre", 80), _largo(t(r.get("apellidos")), "apellidos", 80),
                _largo(t(r.get("telefono")), "telefono", 20, False), _largo(t(r.get("puesto")), "puesto", 60, False),
                _fecha(r.get("fecha_ingreso")))
    email = _largo(t(r.get("email")), "email", 120, False)
    if email and "@" not in email:
        raise ValueError("'email' no es válido")
    return (_largo(t(r.get("nombre")), "nombre", 80), _largo(t(r.get("apellidos")), "apellidos", 80, False),
            _largo(t(r.get("telefono")), "telefono", 20, False), email, _largo(t(r.get("notas")), "notas", 300, False))


def _id_por_nombre(cur, tabla: str, nombre: str, cache: dict, extra_cols: str = "", extra_vals: tuple = ()) -> int:
    clave = (tabla, nombre.lower())
    if clave in cache:
        return cache[clave]
    cur.execute(f"SELECT id FROM {tabla} WHERE nombre = %s", (nombre,))
    f = cur.fetchone()
    if f:
        cache[clave] = f["id"]
    else:
        cur.execute(f"INSERT INTO {tabla} (nombre{extra_cols}) VALUES (%s{',%s' * len(extra_vals)})", (nombre, *extra_vals))
        cache[clave] = cur.lastrowid
    return cache[clave]


def _insertar(cur, sesion, tipo: str, p: tuple, cache: dict) -> bool:
    """Devuelve True si insertó, False si ya existía."""
    if tipo == "servicios":
        cur.execute("SELECT id FROM servicios WHERE nombre = %s", (p[1],))
        if cur.fetchone():
            return False
        cat = _id_por_nombre(cur, "categorias_servicio", p[0], cache)
        cur.execute("INSERT INTO servicios (categoria_id, nombre, unidad, precio) VALUES (%s,%s,%s,%s)", (cat, p[1], p[2], p[3]))
    elif tipo == "insumos":
        cur.execute("SELECT id FROM insumos WHERE nombre = %s", (p[1],))
        if cur.fetchone():
            return False
        cat = _id_por_nombre(cur, "categorias_insumo", p[0], cache)
        prov = _id_por_nombre(cur, "proveedores", p[6], cache) if p[6] else None
        cur.execute("INSERT INTO insumos (categoria_id, proveedor_id, nombre, unidad, existencia, minimo, costo_unitario) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)", (cat, prov, p[1], p[2], p[3], p[4], p[5]))
        nuevo = cur.lastrowid
        if p[3] > 0:
            cur.execute("INSERT INTO movimientos_inventario (insumo_id, usuario_id, tipo, cantidad, costo_unitario, "
                        "existencia_resultante, motivo) VALUES (%s,%s,'entrada',%s,%s,%s,'Existencia inicial')",
                        (nuevo, sesion["id"], p[3], p[5], p[3]))
    elif tipo == "empleados":
        cur.execute("SELECT id FROM empleados WHERE nombre = %s AND apellidos = %s", (p[0], p[1]))
        if cur.fetchone():
            return False
        cur.execute("INSERT INTO empleados (nombre, apellidos, telefono, puesto, fecha_ingreso) VALUES (%s,%s,%s,%s,%s)", p)
    else:
        cur.execute("SELECT id FROM clientes WHERE nombre = %s AND COALESCE(apellidos,'') = %s AND COALESCE(telefono,'') = %s",
                    (p[0], p[1] or "", p[2] or ""))
        if cur.fetchone():
            return False
        cur.execute("INSERT INTO clientes (nombre, apellidos, telefono, email, notas) VALUES (%s,%s,%s,%s,%s)", p)
    return True


def importar(conn, sesion, tipo: str, ruta) -> dict:
    """Importa un archivo. Devuelve {'insertados', 'omitidos', 'errores': [(fila, mensaje)]}."""
    requerir_rol(sesion, "administrador")
    if tipo not in PLANTILLAS:
        raise ErrorNegocio(f"Tipo desconocido. Opciones: {', '.join(PLANTILLAS)}")
    filas = _leer(ruta)
    faltan = _OBLIGATORIAS[tipo] - set(filas[0])
    if faltan:
        raise ErrorNegocio(f"Faltan columnas en el archivo: {', '.join(sorted(faltan))}. "
                           f"Columnas esperadas: {', '.join(PLANTILLAS[tipo])}")
    preparadas, errores = [], []
    for r in filas:
        try:
            preparadas.append(_preparar(tipo, r))
        except ValueError as e:
            errores.append((r["_fila"], str(e)))
    if errores:
        return {"insertados": 0, "omitidos": 0, "errores": errores}
    insertados = omitidos = 0
    cache: dict = {}
    with transaccion(conn) as cur:
        for p in preparadas:
            if _insertar(cur, sesion, tipo, p, cache):
                insertados += 1
            else:
                omitidos += 1
        auditar(cur, sesion, f"carga_inicial_{tipo}", None, None, f"{insertados} nuevos, {omitidos} omitidos")
    return {"insertados": insertados, "omitidos": omitidos, "errores": []}
