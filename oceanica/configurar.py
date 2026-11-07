"""Configura la conexión SIN usar root, cuando la base y el usuario MySQL ya existen:

    python -m oceanica.configurar

Pide los datos del usuario del sistema (por defecto oceanica_app), prueba la conexión,
guarda la configuración en la carpeta de datos y aplica las migraciones pendientes.
"""
from __future__ import annotations

import getpass
import sys

from .config import ConfigDB, guardar_config
from .db import aplicar_migraciones, conectar


def main() -> int:
    print("== Oceánica Gestión: conectar a una base ya creada ==")
    host = input("Servidor MySQL [127.0.0.1]: ").strip() or "127.0.0.1"
    base = input("Nombre de la base [oceanica]: ").strip() or "oceanica"
    usuario = input("Usuario MySQL del sistema [oceanica_app]: ").strip() or "oceanica_app"
    if usuario.lower() == "root":
        print("El sistema no debe usar root. Usa el usuario sugerido (oceanica_app).")
        return 1
    cfg = ConfigDB(host=host, usuario=usuario, password=getpass.getpass(f"Contraseña de {usuario}: "), base=base)
    try:
        conn = conectar(cfg)
    except Exception as e:  # noqa: BLE001
        print("No se pudo conectar:", getattr(e, "msg", e))
        return 1
    print("Configuración guardada en", guardar_config(cfg))
    print("Migraciones aplicadas:", aplicar_migraciones(conn) or "ninguna (ya estaba al día)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
