"""Sonidos y animaciones de la interfaz, en un solo lugar.

- Un filtro de eventos de la aplicación pone sonido a los clics y a los avisos, y anima los campos al escribir:
  brillo suave al entrar a un campo y un pulso por cada tecla.
- `aparecer` (cambio de pantalla), `sacudir` (error) y la aparición suave de los diálogos.
- Todo se apaga con `interfaz_sonidos` / `interfaz_animaciones` (Configuración).

Los sonidos son tonos generados aquí mismo (sin archivos de terceros) y se escriben una vez en la carpeta de datos.
En Windows se tocan con `winsound` (de Python, sin dependencias); en otros sistemas no suenan.
"""
from __future__ import annotations

import logging
import math
import struct
import sys
import time
import wave
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QSequentialAnimationGroup, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QComboBox, QDialog, QGraphicsDropShadowEffect,
                               QLineEdit, QMessageBox, QPlainTextEdit, QTextEdit, QWidget)

from ..config import RAIZ
from . import tema

log = logging.getLogger("oceanica")

_FREC = 22050
# nombre -> notas (frecuencia Hz, duración s) y volumen. Cortos y suaves: es un mostrador, no un videojuego.
_SONIDOS = {
    "clic": ([(1900, 0.018)], 0.16),
    "aviso": ([(880, 0.09), (1175, 0.14)], 0.22),
    "exito": ([(1047, 0.07), (1319, 0.07), (1568, 0.16)], 0.24),
    "error": ([(392, 0.11), (294, 0.18)], 0.26),
    "entrada": ([(784, 0.06), (1047, 0.06), (1319, 0.06), (1568, 0.2)], 0.22),
}
_VERSION = "v1"   # cambiar si cambian los tonos: se regeneran los archivos
_ENTRADAS = (QLineEdit, QAbstractSpinBox, QComboBox, QTextEdit, QPlainTextEdit)


def _generar(ruta: Path, notas, volumen: float) -> None:
    muestras = bytearray()
    for frec, dur in notas:
        n = int(_FREC * dur)
        for i in range(n):
            t = i / _FREC
            ataque = min(1.0, t / 0.004)
            caida = math.exp(-4.5 * t / dur)
            v = volumen * ataque * caida * (math.sin(2 * math.pi * frec * t) + 0.25 * math.sin(4 * math.pi * frec * t))
            muestras += struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32767))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_FREC)
        w.writeframes(bytes(muestras))


class Efectos(QObject):
    def __init__(self):
        super().__init__()
        self.sonidos = True
        self.animaciones = True
        self.historial: list[str] = []          # últimos sonidos pedidos (para pruebas y diagnóstico)
        self._ultimo = 0.0
        self._brillos: dict[int, tuple] = {}     # id(widget) -> (widget, efecto, animación)
        self._vivas: set = set()                 # animaciones en curso (para que no las borre el recolector)
        self._archivos: dict[str, Path] = {}

    # ------------------------------------------------------------------ configuración
    def instalar(self, app) -> None:
        app.installEventFilter(self)

    def configurar(self, sonidos: bool, animaciones: bool) -> None:
        self.sonidos, self.animaciones = sonidos, animaciones

    def configurar_desde(self, conn) -> None:
        from ..servicios import configuracion
        try:
            self.configurar(configuracion.obtener(conn, "interfaz_sonidos", "si") != "no",
                            configuracion.obtener(conn, "interfaz_animaciones", "si") != "no")
        except Exception:   # sin la migración todavía o sin base: se quedan encendidos
            log.exception("No se pudo leer la configuración de sonidos y animaciones")

    # ------------------------------------------------------------------ sonidos
    def _archivo(self, nombre: str) -> Path | None:
        if nombre not in self._archivos:
            ruta = RAIZ / "sonidos" / f"{nombre}_{_VERSION}.wav"
            try:
                if not ruta.exists():
                    _generar(ruta, *_SONIDOS[nombre])
            except OSError:
                log.exception("No se pudo preparar el sonido %s", nombre)
                return None
            self._archivos[nombre] = ruta
        return self._archivos[nombre]

    def reproducir(self, nombre: str) -> None:
        if not self.sonidos or nombre not in _SONIDOS:
            return
        ahora = time.monotonic()
        if nombre == "clic" and ahora - self._ultimo < 0.06:   # un clic no tapa el sonido de lo que provocó
            return
        self._ultimo = ahora
        self.historial = (self.historial + [nombre])[-20:]
        if sys.platform != "win32":
            return
        ruta = self._archivo(nombre)
        if ruta is None:
            return
        try:
            import winsound
            winsound.PlaySound(str(ruta), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except Exception:   # sin tarjeta de sonido, etc.: el sistema sigue igual
            log.debug("No se pudo reproducir %s", nombre, exc_info=True)

    # ------------------------------------------------------------------ animaciones
    def _correr(self, anim) -> None:
        self._vivas.add(anim)
        anim.finished.connect(lambda: self._vivas.discard(anim))
        anim.start()

    def aparecer(self, widget: QWidget, desde: int = 28, ms: int = 220) -> None:
        """Entrada de una pantalla: se desliza un poco desde la derecha (sin efectos gráficos encimados)."""
        if not self.animaciones or widget is None:
            return
        final = widget.pos()
        anim = QPropertyAnimation(widget, b"pos", widget)
        anim.setDuration(ms)
        anim.setStartValue(final + QPoint(desde, 0))
        anim.setEndValue(final)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        self._correr(anim)

    def sacudir(self, widget: QWidget) -> None:
        """Error: el recuadro tiembla un instante."""
        if not self.animaciones or widget is None:
            return
        base = widget.pos()
        grupo = QSequentialAnimationGroup(widget)
        for dx, ms in ((-10, 40), (9, 60), (-6, 60), (4, 50), (0, 40)):
            a = QPropertyAnimation(widget, b"pos")
            a.setDuration(ms)
            a.setEndValue(base + QPoint(dx, 0))
            grupo.addAnimation(a)
        self._correr(grupo)

    def _aparecer_dialogo(self, dlg: QDialog) -> None:
        dlg.setWindowOpacity(0.0)
        anim = QPropertyAnimation(dlg, b"windowOpacity", dlg)
        anim.setDuration(160)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        self._correr(anim)

    @staticmethod
    def _destino(obj) -> QWidget | None:
        if not isinstance(obj, _ENTRADAS):
            return None
        padre = obj.parentWidget()
        if isinstance(obj, QLineEdit) and isinstance(padre, (QComboBox, QAbstractSpinBox)):
            return padre
        return obj

    def _brillo(self, w: QWidget, encender: bool, pulso: bool = False) -> None:
        clave = id(w)
        actual = self._brillos.get(clave)
        if actual is None:
            if not encender or w.graphicsEffect() is not None:   # otro efecto ya ocupa ese campo
                return
            ef = QGraphicsDropShadowEffect(w)
            ef.setOffset(0, 0)
            c = QColor(tema.PRIMARIO)
            c.setAlpha(150)
            ef.setColor(c)
            ef.setBlurRadius(0)
            w.setGraphicsEffect(ef)
            anim = QPropertyAnimation(ef, b"blurRadius", ef)
            anim.finished.connect(lambda: self._al_terminar_brillo(clave))
            self._brillos[clave] = actual = (w, ef, anim)
            w.destroyed.connect(lambda *_: self._brillos.pop(clave, None))
        _, ef, anim = actual
        anim.stop()
        if pulso:
            anim.setDuration(140)
            anim.setKeyValues([(0.0, 26.0), (1.0, 16.0)])
        elif encender:
            anim.setDuration(180)
            anim.setKeyValues([(0.0, ef.blurRadius()), (1.0, 16.0)])
        else:
            anim.setDuration(160)
            anim.setKeyValues([(0.0, ef.blurRadius()), (1.0, 0.0)])
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()

    def _al_terminar_brillo(self, clave: int) -> None:
        actual = self._brillos.get(clave)
        if actual and actual[1].blurRadius() <= 0.01:   # terminó de apagarse: se quita el efecto del campo
            self._quitar_brillo(clave)

    def _quitar_brillo(self, clave: int) -> None:
        actual = self._brillos.pop(clave, None)
        if actual:
            w, ef, _ = actual
            try:
                if w.graphicsEffect() is ef:
                    w.setGraphicsEffect(None)
            except RuntimeError:   # el campo ya no existe
                pass

    # ------------------------------------------------------------------ filtro de eventos
    def eventFilter(self, obj, ev):
        try:
            t = ev.type()
            if t == QEvent.MouseButtonRelease and isinstance(obj, QAbstractButton):
                if ev.button() == Qt.LeftButton and obj.isEnabled() and obj.rect().contains(ev.position().toPoint()):
                    self.reproducir("clic")
            elif t == QEvent.KeyPress:
                if isinstance(obj, QAbstractButton) and ev.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                    self.reproducir("clic")
                elif self.animaciones and ev.text() and obj.hasFocus() and (w := self._destino(obj)) is not None:
                    self._brillo(w, True, pulso=True)
            elif t == QEvent.FocusIn and self.animaciones and (w := self._destino(obj)) is not None:
                self._brillo(w, True)
            elif t == QEvent.FocusOut and (w := self._destino(obj)) is not None and id(w) in self._brillos:
                self._brillo(w, False)
            elif t == QEvent.Show and isinstance(obj, QDialog) and obj.isWindow():
                if isinstance(obj, QMessageBox):
                    icono = obj.icon()
                    if icono in (QMessageBox.Critical, QMessageBox.Warning):
                        self.reproducir("error")
                    else:   # «Listo», «Guardado»… son confirmaciones; las preguntas, aviso
                        self.reproducir("exito" if icono == QMessageBox.Information else "aviso")
                elif getattr(obj, "sonido_al_abrir", None):
                    self.reproducir(obj.sonido_al_abrir)
                if self.animaciones:
                    self._aparecer_dialogo(obj)
        except RuntimeError:   # objeto de Qt que ya se destruyó
            pass
        return False


efectos = Efectos()
