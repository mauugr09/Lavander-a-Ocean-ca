"""Estado compartido de la aplicación: conexión, sesión de administrador e identificación por PIN."""
from __future__ import annotations

from datetime import datetime, timedelta

import mysql.connector

from ..db import conectar

VIGENCIA_IDENTIDAD = timedelta(seconds=120)


class Contexto:
    def __init__(self, conn=None, cfg=None):
        self._conn = conn
        self._cfg = cfg
        self.admin: dict | None = None          # sesión del administrador (contraseña) o None en modo mostrador
        self.ultima: tuple[dict, datetime] | None = None
        self.ultimo_usuario_id: int | None = None
        self.nombre_negocio = ""

    @property
    def conn(self):
        """Conexión viva: si el servidor la cerró por inactividad, se reconecta."""
        if self._cfg is not None:
            try:
                self._conn.ping(reconnect=True, attempts=3, delay=1)
            except mysql.connector.Error:
                self._conn = conectar(self._cfg)
        return self._conn

    @property
    def es_admin(self) -> bool:
        return self.admin is not None

    def identificar(self, parent, sensible: bool = True, titulo: str = "¿Quién realiza esto?"):
        """Devuelve la sesión de quien actúa o None si cancela.

        Administrador con contraseña: actúa con su propia sesión. Modo mostrador: pide el PIN del empleado.
        Acciones no sensibles (consultar, editar clientes) reutilizan la identidad por 2 minutos; las que
        mueven dinero o entregan ropa (sensible=True) siempre piden el PIN.
        """
        if self.admin:
            return self.admin
        if not sensible and self.ultima and datetime.now() - self.ultima[1] < VIGENCIA_IDENTIDAD:
            return self.ultima[0]
        from .dialogos import PinDialog
        dlg = PinDialog(self, parent, titulo)
        if dlg.exec() and dlg.sesion:
            self.ultima = (dlg.sesion, datetime.now())
            self.ultimo_usuario_id = dlg.sesion["id"]
            return dlg.sesion
        return None

    def autorizar_admin(self, parent, titulo: str):
        """Pide usuario y contraseña de la encargada para una excepción. Devuelve su sesión o None."""
        if self.admin:
            return self.admin
        from .dialogos import AutorizacionDialog
        dlg = AutorizacionDialog(self, parent, titulo)
        return dlg.sesion if dlg.exec() else None

    def olvidar_identidad(self) -> None:
        self.ultima = None
