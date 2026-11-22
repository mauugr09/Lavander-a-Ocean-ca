"""Botones «Descargar plantilla» e «Importar desde Excel o CSV», compartidos por las pantallas de la encargada.

La regla (todo o nada, solo administrador, registros repetidos se omiten) vive en `servicios.carga_inicial`;
aquí solo se elige el archivo y se informa el resultado.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton

from ..servicios import carga_inicial
from .util import seguro

NOMBRES = {"servicios": "servicio(s)", "clientes": "cliente(s)", "insumos": "insumo(s)"}


def descargar_plantilla(parent, tipo: str) -> bool:
    ruta, _ = QFileDialog.getSaveFileName(parent, "Guardar plantilla", str(Path.home() / f"plantilla_{tipo}.csv"),
                                          "CSV (*.csv)")
    if ruta and seguro(parent, carga_inicial.generar_plantilla, tipo, ruta)[0]:
        QMessageBox.information(parent, "Oceánica", "Plantilla guardada. Ábrala en Excel, llénela y guárdela como CSV o Excel.")
        return True
    return False


def importar_archivo(parent, ctx, tipo: str) -> bool:
    """Pide el archivo y lo importa con la sesión de la encargada. Devuelve True si se guardó algo."""
    ruta, _ = QFileDialog.getOpenFileName(parent, "Elegir archivo", str(Path.home()), "Excel o CSV (*.xlsx *.csv)")
    if not ruta:
        return False
    ok, r = seguro(parent, carga_inicial.importar, ctx.conn, ctx.admin, tipo, ruta)
    if not ok:
        return False
    if r["errores"]:
        detalle = "\n".join(f"Fila {f}: {m}" for f, m in r["errores"][:15])
        mas = f"\n… y {len(r['errores']) - 15} fila(s) más." if len(r["errores"]) > 15 else ""
        QMessageBox.warning(parent, "Archivo con errores", f"No se importó nada. Corrija estas filas:\n\n{detalle}{mas}")
        return False
    QMessageBox.information(parent, "Importación", f"{r['insertados']} {NOMBRES[tipo]} nuevos, {r['omitidos']} ya existían.")
    return r["insertados"] > 0


def crear_botones(parent, ctx, tipo: str, al_importar) -> tuple[QPushButton, QPushButton]:
    """Devuelve (plantilla, importar) ya conectados. `al_importar` se llama si se guardó algo."""
    b_plantilla = QPushButton("Descargar plantilla")
    b_importar = QPushButton("Importar desde Excel o CSV")
    b_plantilla.clicked.connect(lambda: descargar_plantilla(parent, tipo))
    b_importar.clicked.connect(lambda: importar_archivo(parent, ctx, tipo) and al_importar())
    return b_plantilla, b_importar
