"""Íconos de línea (Tabler Icons, licencia MIT) pintados en el color que se pida.

Los SVG están en recursos/iconos y usan `currentColor`, así que un mismo ícono sirve en
botones blancos, en botones azules y en el menú.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QLabel, QLineEdit

from .tema import TEXTO

CARPETA = Path(__file__).parent / "recursos" / "iconos"


@lru_cache(maxsize=None)
def _svg(nombre: str) -> str:
    return (CARPETA / f"{nombre}.svg").read_text(encoding="utf-8")


def pixmap(nombre: str, color: str = TEXTO, tam: int = 24, grosor: float = 2) -> QPixmap:
    escala = QGuiApplication.instance().devicePixelRatio() if QGuiApplication.instance() else 1
    texto = _svg(nombre).replace("currentColor", color).replace('stroke-width="2"', f'stroke-width="{grosor}"')
    render = QSvgRenderer(QByteArray(texto.encode("utf-8")))
    px = QPixmap(int(tam * escala), int(tam * escala))
    px.fill(Qt.transparent)
    p = QPainter(px)
    render.render(p)
    p.end()
    px.setDevicePixelRatio(escala)
    return px


def icono(nombre: str, color: str = TEXTO, tam: int = 24) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(nombre, color, tam), QIcon.Normal)
    ic.addPixmap(pixmap(nombre, "#9FB0C0", tam), QIcon.Disabled)
    return ic


def poner(boton: QAbstractButton, nombre: str, color: str = TEXTO, tam: int = 22) -> QAbstractButton:
    """Agrega el ícono a la izquierda del texto del botón."""
    boton.setIcon(icono(nombre, color, tam))
    boton.setIconSize(QSize(tam, tam))
    return boton


def en_etiqueta(lb: QLabel, nombre: str, color: str = TEXTO, tam: int = 24, grosor: float = 2) -> QLabel:
    lb.setPixmap(pixmap(nombre, color, tam, grosor))
    return lb


def en_buscador(campo: QLineEdit) -> QLineEdit:
    campo.addAction(icono("search", "#5B6F86", 20), QLineEdit.LeadingPosition)
    return campo
