"""Inventario de insumos: existencias, entradas, salidas, ajustes y alta."""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from ..servicios import inventario
from . import tema
from .dialogos import _botones
from .util import a_decimal, crear_tabla, dinero, etiqueta, fecha_hora, id_seleccionado, numero, poblar, seguro


class InsumoDialog(QDialog):
    def __init__(self, parent, categorias, proveedores):
        super().__init__(parent)
        self.setWindowTitle("Nuevo insumo")
        self.setMinimumWidth(430)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.categoria = QComboBox()
        self.categoria.setEditable(True)
        for c in categorias:
            self.categoria.addItem(c["nombre"], c["id"])
        self.categoria.setCurrentIndex(-1)
        self.nombre = QLineEdit()
        self.unidad = QComboBox()
        self.unidad.setEditable(True)
        self.unidad.addItems(["pieza", "litro", "kg", "bolsa", "caja", "garrafa"])
        self.existencia, self.minimo, self.costo = QLineEdit("0"), QLineEdit("0"), QLineEdit("0")
        self.proveedor = QComboBox()
        self.proveedor.addItem("(sin proveedor)", None)
        for p in proveedores:
            self.proveedor.addItem(p["nombre"], p["id"])
        for etiq, w in (("Categoría (escribe una nueva si hace falta)", self.categoria), ("Nombre", self.nombre),
                        ("Unidad", self.unidad), ("Existencia actual", self.existencia), ("Mínimo (avisa debajo de esto)", self.minimo),
                        ("Costo por unidad $", self.costo), ("Proveedor", self.proveedor)):
            form.addRow(etiq, w)
        lay.addLayout(form)
        bb = _botones(self, "Guardar")
        bb.accepted.connect(self._validar)
        lay.addWidget(bb)
        self.nombre.setFocus()

    def _validar(self):
        if not self.categoria.currentText().strip() or not self.nombre.text().strip():
            QMessageBox.warning(self, "Oceánica", "Escribe la categoría y el nombre.")
            return
        for w in (self.existencia, self.minimo, self.costo):
            v = a_decimal(w.text())
            if v is None or v < 0:
                QMessageBox.warning(self, "Oceánica", "Existencia, mínimo y costo deben ser números de cero en adelante.")
                return
        self.accept()


class MovimientoDialog(QDialog):
    def __init__(self, parent, titulo: str, pide_costo: bool, solo_motivo_obligatorio: bool = False, texto_cantidad="Cantidad"):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.addWidget(etiqueta(titulo, "subtitulo"))
        form = QFormLayout()
        self.cantidad, self.motivo, self.costo = QLineEdit(), QLineEdit(), QLineEdit()
        self.motivo.setPlaceholderText("Obligatorio" if solo_motivo_obligatorio else "Opcional (compra, consumo, merma…)")
        self.obligatorio = solo_motivo_obligatorio
        form.addRow(texto_cantidad, self.cantidad)
        if pide_costo:
            self.costo.setPlaceholderText("Opcional")
            form.addRow("Costo por unidad $", self.costo)
        form.addRow("Motivo", self.motivo)
        lay.addLayout(form)
        bb = _botones(self, "Registrar")
        bb.accepted.connect(self._validar)
        lay.addWidget(bb)
        self.cantidad.setFocus()

    def _validar(self):
        if a_decimal(self.cantidad.text()) is None:
            QMessageBox.warning(self, "Oceánica", "Escribe una cantidad válida.")
            return
        if self.obligatorio and not self.motivo.text().strip():
            QMessageBox.warning(self, "Oceánica", "Escribe el motivo.")
            return
        self.accept()


class InventarioView(QWidget):
    titulo = "Inventario"

    def __init__(self, ctx):
        super().__init__()
        self.setObjectName("pagina")
        self.ctx = ctx
        self.filas: dict[int, dict] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.addWidget(etiqueta("Inventario", "titulo"))
        fila = QHBoxLayout()
        self.buscar = QLineEdit()
        self.buscar.setPlaceholderText("Buscar insumo")
        self.solo_bajos = QCheckBox("Solo los que están bajos")
        self.b_nuevo = QPushButton("Nuevo insumo")
        self.b_nuevo.setProperty("rol", "primario")
        self.b_entrada = QPushButton("Entrada (compra)")
        self.b_salida = QPushButton("Salida (consumo / merma)")
        self.b_ajuste = QPushButton("Ajustar al conteo")
        self.b_hist = QPushButton("Historial")
        fila.addWidget(self.buscar, 1)
        fila.addWidget(self.solo_bajos)
        lay.addLayout(fila)
        botones = QHBoxLayout()
        for b in (self.b_entrada, self.b_salida, self.b_hist):
            botones.addWidget(b)
        botones.addStretch(1)
        botones.addWidget(self.b_ajuste)
        botones.addWidget(self.b_nuevo)
        lay.addLayout(botones)
        self.tabla = crear_tabla(["Insumo", "Categoría", "Existencia", "Mínimo", "Costo", "Proveedor", "Estado"],
                                 derecha=(2, 3, 4), estirar=0)
        lay.addWidget(self.tabla, 1)
        self.b_nuevo.setVisible(ctx.es_admin)
        self.b_ajuste.setVisible(ctx.es_admin)
        self.buscar.textChanged.connect(self.recargar)
        self.solo_bajos.toggled.connect(self.recargar)
        self.b_nuevo.clicked.connect(self.nuevo)
        self.b_entrada.clicked.connect(lambda: self.mover("entrada"))
        self.b_salida.clicked.connect(lambda: self.mover("salida"))
        self.b_ajuste.clicked.connect(self.ajustar)
        self.b_hist.clicked.connect(self.historial)

    def al_mostrar(self):
        self.b_nuevo.setVisible(self.ctx.es_admin)
        self.b_ajuste.setVisible(self.ctx.es_admin)
        self.recargar()
        self.buscar.setFocus()

    def recargar(self):
        ok, filas = seguro(self, inventario.listar_insumos, self.ctx.conn, self.solo_bajos.isChecked(), self.buscar.text() or None)
        self.filas = {i["id"]: i for i in filas or []}
        poblar(self.tabla, [(i["id"], [i["nombre"], i["categoria"], f"{numero(i['existencia'])} {i['unidad']}", numero(i['minimo']),
                                       dinero(i["costo_unitario"]), i["proveedor"] or "", "BAJO" if i["bajo"] else "OK"])
                            for i in self.filas.values()],
               lambda i: QColor(tema.ERROR) if self.filas[i]["bajo"] else None)

    def _actual(self) -> dict | None:
        i = id_seleccionado(self.tabla)
        if i is None:
            QMessageBox.information(self, "Oceánica", "Selecciona un insumo de la lista.")
            return None
        return self.filas[i]

    def nuevo(self):
        dlg = InsumoDialog(self, inventario.listar_categorias(self.ctx.conn), inventario.listar_proveedores(self.ctx.conn))
        if not dlg.exec():
            return
        nombre_cat = dlg.categoria.currentText().strip()
        k = dlg.categoria.findText(nombre_cat)
        cat_id = dlg.categoria.itemData(k) if k >= 0 else None
        if cat_id is None:
            ok, cat_id = seguro(self, inventario.crear_categoria, self.ctx.conn, self.ctx.admin, nombre_cat)
            if not ok:
                return
        ok, _ = seguro(self, inventario.crear_insumo, self.ctx.conn, self.ctx.admin, cat_id, dlg.nombre.text(),
                       dlg.unidad.currentText(), a_decimal(dlg.minimo.text()), a_decimal(dlg.costo.text()),
                       dlg.proveedor.currentData(), a_decimal(dlg.existencia.text()))
        if ok:
            self.recargar()

    def mover(self, tipo: str):
        i = self._actual()
        if not i:
            return
        titulo = f"{'Entrada' if tipo == 'entrada' else 'Salida'}: {i['nombre']} ({i['unidad']})"
        dlg = MovimientoDialog(self, titulo, pide_costo=tipo == "entrada")
        if not dlg.exec():
            return
        sesion = self.ctx.identificar(self, sensible=True, titulo="Confirma con tu PIN")
        if not sesion:
            return
        ok, _ = seguro(self, inventario.registrar_movimiento, self.ctx.conn, sesion, i["id"], tipo, a_decimal(dlg.cantidad.text()),
                       dlg.motivo.text() or None, a_decimal(dlg.costo.text()) if dlg.costo.text().strip() else None)
        if ok:
            self.recargar()

    def ajustar(self):
        i = self._actual()
        if not i:
            return
        dlg = MovimientoDialog(self, f"Ajustar a conteo físico: {i['nombre']}", False, True, "Existencia real contada")
        if dlg.exec():
            ok, _ = seguro(self, inventario.ajustar_existencia, self.ctx.conn, self.ctx.admin, i["id"],
                           a_decimal(dlg.cantidad.text()), dlg.motivo.text())
            if ok:
                self.recargar()

    def historial(self):
        i = self._actual()
        if not i:
            return
        ok, movs = seguro(self, inventario.movimientos_insumo, self.ctx.conn, i["id"])
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Historial: {i['nombre']}")
        dlg.resize(760, 420)
        lay = QVBoxLayout(dlg)
        t = crear_tabla(["Fecha", "Tipo", "Cantidad", "Existencia", "Motivo", "Quién"], derecha=(2, 3), estirar=4)
        poblar(t, [(m["id"], [fecha_hora(m["creado_en"]), m["tipo"], numero(m['cantidad']),
                              numero(m['existencia_resultante']) if m["existencia_resultante"] is not None else "",
                              m["motivo"] or "", m["usuario"]]) for m in movs or []])
        lay.addWidget(t)
        cerrar = QPushButton("Cerrar")
        cerrar.clicked.connect(dlg.accept)
        lay.addWidget(cerrar)
        dlg.exec()
