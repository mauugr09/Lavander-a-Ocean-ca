"""Actualiza la base de datos a la última versión del sistema.

Uso:
    python -m oceanica.migrar                 (o OceanicaAdmin.exe migrar; el instalador lo corre solo)
    python -m oceanica.migrar --sin-respaldo  (solo si el respaldo previo no se puede hacer y ya hay otro reciente)

Aplica solo las migraciones pendientes. Si hay alguna y la base ya tiene datos, primero hace un respaldo:
una migración que falla a la mitad no se puede deshacer sola (MySQL confirma cada cambio de estructura),
y ese respaldo es lo que permite volver atrás. Si el respaldo falla, no se cambia nada.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from . import respaldos
from .config import CARPETA_MIGRACIONES, CARPETA_RESPALDOS, ConfigDB, cargar_config
from .db import aplicar_migraciones, conectar, migraciones_pendientes

log = logging.getLogger("oceanica")


class ErrorActualizacion(Exception):
    """La actualización no se hizo o quedó a medias; el mensaje dice qué hacer."""


def actualizar(cfg: ConfigDB, carpeta: Path = CARPETA_MIGRACIONES, carpeta_respaldos: Path = CARPETA_RESPALDOS,
               sin_respaldo: bool = False) -> dict:
    """{'aplicadas': [...], 'respaldo': Path | None}. Lanza ErrorActualizacion si no se pudo."""
    conn = conectar(cfg)
    try:
        pendientes, con_datos = migraciones_pendientes(conn, carpeta)
        if not pendientes:
            return {"aplicadas": [], "respaldo": None}
        respaldo = None
        if con_datos and not sin_respaldo:
            try:
                respaldo = respaldos.crear_respaldo("automatico", cfg=cfg, carpeta=carpeta_respaldos)
            except Exception as e:  # mysqldump ausente, disco lleno, sin permisos…
                log.exception("No se pudo hacer el respaldo previo a la actualización")
                raise ErrorActualizacion(
                    f"No se pudo hacer el respaldo antes de actualizar ({e}).\n"
                    "No se cambió nada en la base. Corrija el problema y vuelva a intentar; si ya tiene un "
                    "respaldo de hoy, puede usar: migrar --sin-respaldo") from e
        try:
            aplicadas = aplicar_migraciones(conn, carpeta)
        except Exception as e:
            log.exception("Falló una migración")
            como_volver = (f"python -m oceanica.respaldos --restaurar \"{respaldo}\"" if respaldo
                           else "restaure el respaldo más reciente")
            raise ErrorActualizacion(f"Error al actualizar la base: {e}\n"
                                     f"La base puede haber quedado a medias. Para volver a como estaba: {como_volver}") from e
        return {"aplicadas": aplicadas, "respaldo": respaldo}
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        cfg = cargar_config()
        r = actualizar(cfg, sin_respaldo="--sin-respaldo" in argv)
    except ErrorActualizacion as e:
        print(e)
        return 1
    except Exception as e:  # noqa: BLE001 — sin conexión: el mensaje lo lee quien instala
        print(f"No se pudo conectar a la base de datos: {e}")
        return 1
    if r["respaldo"]:
        print("Respaldo previo:", r["respaldo"])
    print("Migraciones aplicadas:", r["aplicadas"] or "ninguna (ya estaba al día)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
