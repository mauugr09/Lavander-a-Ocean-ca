"""Catálogo de servicios y precios (administrador)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from ..servicios import carga_inicial, catalogo
from . import tema
from .dialogos import _botones
from .util import a_decimal, crear_tabla, dinero, etiqueta, id_seleccionado, poblar, seguro


class ServicioDialog(QDialog):
    def __init__(self, parent, categorias: list[dict], datos: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Servicio")
        self.setMinimumWidth(420)
        d = datos or {}
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.categoria = QComboBox()
        self.categoria.setEditable(True)
        for c in categorias:
            self.categoria.addItem(c["nombre"], c["id"])
        if d:
            self.categoria.setCurrentIndex(max(0, self.categoria.findData(d["categoria_id"])))
        else:
            self.categoria.setCurrentIndex(-1)
            self.categoria.setEditText("")
        self.nombre = QLineEdit(d.get("nombre", ""))
        self.unidad = QComboBox()
        self.unidad.addItem("Por kilo", "kilo")
        self.unidad.addItem("Por pieza", "pieza")
        if d:
            self.unidad.setCurrentIndex(self.unidad.findData(d["unidad"]))
        self.precio = QLineEdit(f"{d['precio']:.2f}" if d else "")
        form.addRow("Categoría (escribe una nueva si hace falta)", self.categoria)
        form.addRow("Nombre", self.nombre)
        form.addRow("Se cobra", self.unidad)
        form.addRow("Precio $", self.precio)
        lay.addLayout(form)
        bb = _botones(self, "Guardar")
        bb.accepted.connect(self._validar)
        lay.addWidget(bb)
        self.nombre.setFocus()

    def _validar(self):
        if not self.categoria.currentText().strip() or not self.nombre.text().strip():
            QMessageBox.warning(self, "Oceánica", "Escribe la categoría y el nombre del servicio.")
            return
        p = a_decimal(self.precio.text())
        if p is None or p < 0:
            QMessageBox.warning(self, "Oceánica", "Escribe un precio válido.")
            return
        self.accept()

    def valores(self):
        nombre_cat = self.categoria.currentText().strip()
        i = self.categoria.findText(nombre_cat, Qt.MatchFixedString)  # sin distinguir mayúsculas
        cat_id = self.categoria.itemData(i) if i >= 0 else None
        return nombre_cat, cat_id, self.nombre.text().strip(), self.unidad.currentData(), a_decimal(self.precio.text())


class CatalogoView(QWidget):
    titulo = "Servicios y precios"

    def __init__(self, ctx):
        super().__init__()
        self.setObjectName("pagina")
        self.ctx = ctx
        self.filas: dict[int, dict] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.addWidget(etiqueta("Servicios y precios", "titulo"))
        fila = QHBoxLayout()
        self.b_nuevo = QPushButton("Nuevo servicio")
        self.b_nuevo.setProperty("rol", "primario")
        self.b_editar = QPushButton("Editar / cambiar precio")
        self.b_estado = QPushButton("Activar / desactivar")
        self.b_plantilla = QPushButton("Descargar plantilla")
        self.b_importar = QPushButton("Importar desde Excel o CSV")
        for b in (self.b_nuevo, self.b_editar, self.b_estado):
            fila.addWidget(b)
        fila.addStretch(1)
        fila.addWidget(self.b_plantilla)
        fila.addWidget(self.b_importar)
        lay.addLayout(fila)
        self.tabla = crear_tabla(["Categoría", "Servicio", "Se cobra", "Precio", "Estado"], derecha=(3,), estirar=1)
        lay.addWidget(self.tabla, 1)
        lay.addWidget(etiqueta("Cambiar un precio no modifica las órdenes ya creadas: cada orden guarda el precio de ese día.", "suave", True))
        self.b_nuevo.clicked.connect(self.nuevo)
        self.b_editar.clicked.connect(self.editar)
        self.tabla.itemActivated.connect(lambda *_: self.editar())
        self.b_estado.clicked.connect(self.alternar)
        self.b_plantilla.clicked.connect(self.plantilla)
        self.b_importar.clicked.connect(self.importar)

    def al_mostrar(self):
        ok, filas = seguro(self, catalogo.listar_servicios, self.ctx.conn, False)
        self.filas = {s["id"]: s for s in filas or []}
        poblar(self.tabla, [(s["id"], [s["categoria"], s["nombre"], "kilo" if s["unidad"] == "kilo" else "pieza",
                                       dinero(s["precio"]), "Activo" if s["activo"] else "Inactivo"]) for s in self.filas.values()],
               lambda i: None if self.filas[i]["activo"] else QColor(tema.TEXTO_SUAVE))

    def _categoria_id(self, nombre: str, id_: int | None) -> int | None:
        if id_:
            return id_
        ok, nuevo = seguro(self, catalogo.crear_categoria, self.ctx.conn, self.ctx.admin, nombre)
        return nuevo if ok else None

    def nuevo(self):
        cats = catalogo.listar_categorias(self.ctx.conn)
        dlg = ServicioDialog(self, cats)
        if not dlg.exec():
            return
        cat_nombre, cat_id, nombre, unidad, precio = dlg.valores()
        cat_id = self._categoria_id(cat_nombre, cat_id)
        if cat_id and seguro(self, catalogo.crear_servicio, self.ctx.conn, self.ctx.admin, cat_id, nombre, unidad, precio)[0]:
            self.al_mostrar()

    def editar(self):
        sid = id_seleccionado(self.tabla)
        if sid is None:
            return
        dlg = ServicioDialog(self, catalogo.listar_categorias(self.ctx.conn), self.filas[sid])
        if not dlg.exec():
            return
        cat_nombre, cat_id, nombre, unidad, precio = dlg.valores()
        cat_id = self._categoria_id(cat_nombre, cat_id)
        if cat_id and seguro(self, catalogo.actualizar_servicio, self.ctx.conn, self.ctx.admin, sid, nombre, unidad, precio, cat_id)[0]:
            self.al_mostrar()

    def alternar(self):
        sid = id_seleccionado(self.tabla)
        if sid is not None and seguro(self, catalogo.cambiar_estado_servicio, self.ctx.conn, self.ctx.admin, sid,
                                      not self.filas[sid]["activo"])[0]:
            self.al_mostrar()

    def plantilla(self):
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar plantilla", str(Path.home() / "plantilla_servicios.csv"), "CSV (*.csv)")
        if ruta and seguro(self, carga_inicial.generar_plantilla, "servicios", ruta)[0]:
            QMessageBox.information(self, "Oceánica", "Plantilla guardada. Ábrela en Excel, llénala y guárdala como CSV o Excel.")

    def importar(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Elegir archivo", str(Path.home()), "Excel o CSV (*.xlsx *.csv)")
        if not ruta:
            return
        ok, r = seguro(self, carga_inicial.importar, self.ctx.conn, self.ctx.admin, "servicios", ruta)
        if not ok:
            return
        if r["errores"]:
            detalle = "\n".join(f"Fila {f}: {m}" for f, m in r["errores"][:15])
            QMessageBox.warning(self, "Archivo con errores", f"No se importó nada. Corrige estas filas:\n\n{detalle}")
            return
        QMessageBox.information(self, "Importación", f"{r['insertados']} servicio(s) nuevos, {r['omitidos']} ya existían.")
        self.al_mostrar()
