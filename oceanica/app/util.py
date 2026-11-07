"""Formatos, manejo de errores y piezas de interfaz compartidas."""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import mysql.connector
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHeaderView, QLabel, QMessageBox, QTableWidget,
                               QTableWidgetItem)

from ..seguridad import ErrorAcceso
from ..servicios.comunes import ErrorNegocio

log = logging.getLogger("oceanica")

ESTADOS = {"recibida": "Recibida", "en_proceso": "En proceso", "lista": "Lista", "entregada": "Entregada",
           "cancelada": "Cancelada"}
UNIDADES = {"kilo": "kg", "pieza": "pza"}


def dinero(v) -> str:
    return f"${Decimal(v or 0):,.2f}"


def fecha_hora(v) -> str:
    return v.strftime("%d/%m/%Y %H:%M") if isinstance(v, datetime) else (v.strftime("%d/%m/%Y") if isinstance(v, date) else "")


def hora(v) -> str:
    return v.strftime("%H:%M") if isinstance(v, datetime) else ""


def a_decimal(texto: str) -> Decimal | None:
    """Convierte lo que el usuario escribió ('1,250.50', '$40', '2,5') en Decimal; None si no es número."""
    s = (texto or "").replace("$", "").replace(" ", "")
    if not s:
        return None
    s = s.replace(",", ".") if ("," in s and "." not in s) else s.replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def numero(v) -> str:
    """4.00 -> '4', 1.50 -> '1.5' (sin ceros sobrantes)."""
    return format(Decimal(v or 0).normalize(), "f")


def cantidad_txt(c, unidad: str) -> str:
    c = Decimal(c)
    return (f"{c:g}" if unidad == "kilo" else f"{int(c)}") + f" {UNIDADES.get(unidad, unidad)}"


def seguro(parent, fn, *args, **kwargs):
    """Ejecuta fn y muestra al usuario los errores de negocio. Devuelve (ok, resultado)."""
    try:
        return True, fn(*args, **kwargs)
    except (ErrorNegocio, ErrorAcceso, ValueError) as e:
        QMessageBox.warning(parent, "Oceánica", str(e))
    except mysql.connector.Error as e:
        log.exception("Error de base de datos")
        QMessageBox.critical(parent, "Oceánica",
                             "No se pudo completar la operación por un problema con la base de datos.\n"
                             "Revisa que el servicio de MariaDB/MySQL esté encendido y vuelve a intentar.\n\n"
                             f"Detalle: {e}")
    except Exception:
        log.exception("Error inesperado")
        QMessageBox.critical(parent, "Oceánica", "Ocurrió un error inesperado. Quedó registrado en la carpeta logs.")
    return False, None


def etiqueta(texto: str = "", rol: str | None = None, palabra: bool = False) -> QLabel:
    lb = QLabel(texto)
    if rol:
        lb.setProperty("rol", rol)
    lb.setWordWrap(palabra)
    return lb


def tarjeta() -> QFrame:
    f = QFrame()
    f.setProperty("rol", "tarjeta")
    return f


def chip(lb: QLabel, texto: str, rol: str) -> None:
    lb.setText(texto)
    lb.setProperty("rol", rol)
    lb.style().unpolish(lb)
    lb.style().polish(lb)


def crear_tabla(columnas: list[str], derecha: tuple[int, ...] = (), estirar: int = 0) -> QTableWidget:
    """Tabla de solo lectura. Las columnas se ajustan a su contenido y la columna `estirar` ocupa el resto."""
    t = QTableWidget(0, len(columnas))
    t.setHorizontalHeaderLabels(columnas)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    t.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(34)
    h = t.horizontalHeader()
    h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    h.setMinimumSectionSize(70)
    h.setStretchLastSection(False)
    for i in range(len(columnas)):
        h.setSectionResizeMode(i, QHeaderView.Stretch if i == estirar else QHeaderView.ResizeToContents)
    t.setProperty("derecha", derecha)
    return t


def poblar(t: QTableWidget, filas: list[tuple[object, list[str]]], resaltar=None) -> None:
    """filas = [(id_registro, [texto_col0, texto_col1, ...])]. resaltar(id) -> color o None."""
    derecha = t.property("derecha") or ()
    sel = None
    fila_sel = t.currentRow()
    if 0 <= fila_sel < t.rowCount():
        sel = t.item(fila_sel, 0).data(Qt.UserRole)
    t.setRowCount(len(filas))
    reselecc = -1
    for r, (ident, celdas) in enumerate(filas):
        for c, texto in enumerate(celdas):
            it = QTableWidgetItem(str(texto))
            if c == 0:
                it.setData(Qt.UserRole, ident)
            if c in derecha:
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if resaltar and (color := resaltar(ident)):
                it.setForeground(color)
            t.setItem(r, c, it)
        if sel is not None and ident == sel:
            reselecc = r
    if reselecc >= 0:
        t.selectRow(reselecc)


def id_seleccionado(t: QTableWidget):
    r = t.currentRow()
    return t.item(r, 0).data(Qt.UserRole) if r >= 0 and t.item(r, 0) else None
