"""Actualiza la base de datos a la última versión del sistema.

Uso:
    python -m oceanica.migrar

Aplica solo las migraciones pendientes (por ejemplo, después de instalar una versión nueva).
Haz un respaldo antes: python -m oceanica.respaldos --manual
"""
from __future__ import annotations

import sys

from .config import cargar_config
from .db import aplicar_migraciones, conectar


def main() -> int:
    try:
        conn = conectar(cargar_config())
    except Exception as e:
        print(f"No se pudo conectar a la base de datos: {e}")
        return 1
    try:
        aplicadas = aplicar_migraciones(conn)
    except Exception as e:
        print(f"Error al migrar: {e}\nRestaura el respaldo si la base quedó a medias.")
        return 1
    finally:
        conn.close()
    print("Migraciones aplicadas:", aplicadas or "ninguna (ya estaba al día)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
