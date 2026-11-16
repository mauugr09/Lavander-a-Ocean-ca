"""Piezas visuales del mostrador: botones grandes con ícono y teclado numérico para los kilos."""
from __future__ import annotations

import unicodedata
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
                               QVBoxLayout)

from .tema import PRIMARIO, PRIMARIO_OSCURO, SECUNDARIO, TEXTO, TEXTO_SUAVE
from .util import a_decimal, dinero, etiqueta

# Colores suaves por categoría (fondo, borde): ayudan a reconocer cada botón de un vistazo.
COLORES = [
    ("#E6F0FF", "#9DBBF0"),
    ("#E3F6FA", "#8FD3E3"),
    ("#F0E8F7", "#C3A6DA"),
    ("#E5F5EC", "#9BD3B4"),
    ("#FFF1E0", "#F0C48A"),
    ("#FCE8EC", "#E9A9B7"),
    ("#FFF8D6", "#E6CF6E"),
    ("#EEF1F5", "#B9C4D2"),
]

# Ícono según palabras del nombre de la categoría (sin acentos ni mayúsculas).
_ICONOS = [
    ("kilo", "🧺"), ("colcha", "🛏️"), ("edredon", "🛏️"), ("cobija", "🧶"), ("chamarra", "🧥"),
    ("abrigo", "🧥"), ("cojin", "🛋️"), ("cortina", "🏠"), ("calzado", "👟"), ("zapato", "👟"),
    ("tenis", "👟"), ("plancha", "👔"), ("tintorer", "👗"), ("otro", "➕"),
]


def normalizar(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def icono_para(nombre: str) -> str:
    n = normalizar(nombre)
    return next((ico for clave, ico in _ICONOS if clave in n), "🧺")


def es_categoria_kilo(nombre: str) -> bool:
    return "kilo" in normalizar(nombre)


class BotonGrande(QPushButton):
    """Botón con ícono grande, título y una línea de detalle."""

    def __init__(self, icono: str, titulo: str, detalle: str = "", colores=COLORES[0], alto: int = 104,
                 destacado: bool = False):
        super().__init__()
        self.setMinimumHeight(alto)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(titulo)
        fondo, borde = colores
        texto, suave = (("white", "#DCEBFF") if destacado else (TEXTO, TEXTO_SUAVE))
        if destacado:
            estilo = (f"QPushButton {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {PRIMARIO}, "
                      f"stop:1 {SECUNDARIO}); border: none; border-radius: 14px; }}"
                      f"QPushButton:hover {{ background: {PRIMARIO_OSCURO}; }}"
                      f"QPushButton:focus {{ border: 3px solid #FFD54A; }}")
        else:
            estilo = (f"QPushButton {{ background: {fondo}; border: 2px solid {borde}; border-radius: 14px; }}"
                      f"QPushButton:hover {{ border: 2px solid {PRIMARIO}; }}"
                      f"QPushButton:pressed {{ background: white; }}"
                      f"QPushButton:focus {{ border: 3px solid {PRIMARIO}; }}")
        self.setStyleSheet(estilo)

        lay = QHBoxLayout(self) if destacado else QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(4 if not destacado else 16)
        self.lb_icono = QLabel(icono)
        self.lb_icono.setStyleSheet(f"font-size: {38 if destacado else 30}pt;")  # la hoja global fija 10.5pt
        self.lb_icono.setAlignment(Qt.AlignCenter)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        self.lb_titulo = QLabel(titulo)
        self.lb_titulo.setStyleSheet(f"font-size: {17 if destacado else 13}pt; font-weight: 700; color: {texto};")
        self.lb_titulo.setWordWrap(True)
        self.lb_detalle = QLabel(detalle)
        self.lb_detalle.setStyleSheet(f"font-size: {11 if destacado else 10}pt; color: {suave};")
        self.lb_detalle.setWordWrap(True)
        self.lb_detalle.setVisible(bool(detalle))
        for lb in (self.lb_icono, self.lb_titulo, self.lb_detalle):
            lb.setAttribute(Qt.WA_TransparentForMouseEvents)
            lb.setStyleSheet(lb.styleSheet() + "background: transparent;")
        if destacado:
            self.lb_titulo.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.lb_detalle.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            lay.addWidget(self.lb_icono)
            textos.addStretch(1)
            textos.addWidget(self.lb_titulo)
            textos.addWidget(self.lb_detalle)
            textos.addStretch(1)
            lay.addLayout(textos, 1)
        else:
            self.lb_titulo.setAlignment(Qt.AlignCenter)
            self.lb_detalle.setAlignment(Qt.AlignCenter)
            lay.addWidget(self.lb_icono)
            lay.addWidget(self.lb_titulo)
            lay.addWidget(self.lb_detalle)


class KilosDialog(QDialog):
    """Teclado numérico grande para escribir los kilos que marcó la báscula."""

    def __init__(self, parent, servicio: dict, actual: Decimal | None = None):
        super().__init__(parent)
        self.servicio, self.kilos = servicio, None
        self.precio = Decimal(servicio["precio"])
        self.setWindowTitle("¿Cuántos kilos?")
        self.setModal(True)
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(etiqueta(f"🧺  {servicio['nombre']}", "subtitulo"))
        lay.addWidget(etiqueta(f"{dinero(self.precio)} por kilo · Pesa la ropa y escribe los kilos", "suave", True))

        self.pantalla = QLineEdit("" if actual is None else format(actual.normalize(), "f"))
        self.pantalla.setAlignment(Qt.AlignRight)
        self.pantalla.setPlaceholderText("0")
        self.pantalla.setStyleSheet("font-size: 30pt; font-weight: 700; padding: 6px 12px;")
        fila = QHBoxLayout()
        fila.addWidget(self.pantalla, 1)
        kg = QLabel("kg")
        kg.setStyleSheet("font-size: 20pt; font-weight: 600;")
        fila.addWidget(kg)
        lay.addLayout(fila)

        rejilla = QGridLayout()
        rejilla.setSpacing(8)
        teclas = ["7", "8", "9", "4", "5", "6", "1", "2", "3", ".", "0", "⌫"]
        for i, t in enumerate(teclas):
            b = QPushButton(t)
            b.setMinimumSize(86, 64)
            b.setFocusPolicy(Qt.NoFocus)
            b.setStyleSheet("font-size: 20pt; font-weight: 600; border-radius: 10px;")
            b.clicked.connect(lambda _=False, t=t: self._tecla(t))
            rejilla.addWidget(b, i // 3, i % 3)
        lay.addLayout(rejilla)

        self.lb_importe = etiqueta("", "titulo")
        self.lb_importe.setAlignment(Qt.AlignRight)
        lay.addWidget(self.lb_importe)
        self.msg = etiqueta("", "error")
        lay.addWidget(self.msg)

        botones = QHBoxLayout()
        cancelar = QPushButton("Cancelar")
        cancelar.setMinimumHeight(52)
        self.b_ok = QPushButton("✔  Agregar" if actual is None else "✔  Cambiar")
        self.b_ok.setProperty("rol", "primario")
        self.b_ok.setMinimumHeight(52)
        self.b_ok.setStyleSheet("font-size: 14pt;")
        botones.addWidget(cancelar, 1)
        botones.addWidget(self.b_ok, 2)
        lay.addLayout(botones)

        cancelar.clicked.connect(self.reject)
        self.b_ok.clicked.connect(self._aceptar)
        self.pantalla.returnPressed.connect(self._aceptar)
        self.pantalla.textChanged.connect(self._actualizar)
        self._actualizar()
        self.pantalla.setFocus()

    def _tecla(self, t: str):
        s = self.pantalla.text()
        if t == "⌫":
            s = s[:-1]
        elif t == ".":
            s = s if "." in s else (s or "0") + "."
        elif len(s) < 7:
            s += t
        self.pantalla.setText(s)

    def _actualizar(self):
        k = a_decimal(self.pantalla.text())
        self.lb_importe.setText(f"Total: {dinero(self.precio * k)}" if k and k > 0 else "Total: $0.00")
        self.msg.setText("")

    def _aceptar(self):
        k = a_decimal(self.pantalla.text())
        if k is None or k <= 0:
            self.msg.setText("Escribe los kilos (mayor que cero).")
            return
        self.kilos = k
        self.accept()
