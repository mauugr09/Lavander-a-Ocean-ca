"""Configuración de conexión. Nunca se guardan contraseñas en el código.

Orden de lectura: variables de entorno (OCEANICA_DB_*) y luego config.ini.

config.ini, los respaldos, los logs y los tickets viven en una carpeta de datos
FUERA de la carpeta del programa (en Windows: %APPDATA%\\OceanicaGestion), para que
actualizar o descomprimir una versión nueva no obligue a configurar de nuevo.
Si existe un config.ini junto al programa (instalaciones anteriores) se sigue usando.
"""
from __future__ import annotations

import configparser
import os
import sys
from dataclasses import dataclass
from pathlib import Path

if getattr(sys, "frozen", False):  # ejecutable de PyInstaller: los recursos van dentro del paquete
    CARPETA_PROGRAMA = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    _CARPETA_EXE = Path(sys.executable).parent
else:
    CARPETA_PROGRAMA = Path(__file__).resolve().parent.parent
    _CARPETA_EXE = CARPETA_PROGRAMA
CARPETA_MIGRACIONES = CARPETA_PROGRAMA / "db" / "migrations"


def _carpeta_datos() -> Path:
    if os.environ.get("OCEANICA_HOME"):
        return Path(os.environ["OCEANICA_HOME"])
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home()) / "OceanicaGestion"
    return Path.home() / ".oceanica"


RAIZ = _carpeta_datos()  # datos del negocio: configuración, respaldos, logs, tickets
RUTA_CONFIG = RAIZ / "config.ini"
_RUTA_CONFIG_ANTIGUA = _CARPETA_EXE / "config.ini"
if not RUTA_CONFIG.exists() and _RUTA_CONFIG_ANTIGUA.exists():
    RUTA_CONFIG = _RUTA_CONFIG_ANTIGUA
CARPETA_RESPALDOS = RAIZ / "respaldos"
CARPETA_LOGS = RAIZ / "logs"


@dataclass(frozen=True)
class ConfigDB:
    host: str = "127.0.0.1"
    port: int = 3306
    usuario: str = "oceanica_app"
    password: str = ""
    base: str = "oceanica"


def cargar_config(ruta: Path | None = None) -> ConfigDB:
    ruta = ruta or RUTA_CONFIG
    valores: dict[str, str] = {}
    if ruta.exists():
        cp = configparser.ConfigParser()
        cp.read(ruta, encoding="utf-8")
        if cp.has_section("mysql"):
            valores = dict(cp["mysql"])
    env = {
        "host": os.environ.get("OCEANICA_DB_HOST"),
        "port": os.environ.get("OCEANICA_DB_PORT"),
        "usuario": os.environ.get("OCEANICA_DB_USER"),
        "password": os.environ.get("OCEANICA_DB_PASSWORD"),
        "base": os.environ.get("OCEANICA_DB_NAME"),
    }
    valores.update({k: v for k, v in env.items() if v})
    if "port" in valores:
        valores["port"] = int(valores["port"])  # type: ignore[assignment]
    return ConfigDB(**valores)  # type: ignore[arg-type]


def guardar_config(cfg: ConfigDB, ruta: Path | None = None) -> Path:
    """Escribe config.ini y restringe permisos en sistemas POSIX."""
    ruta = ruta or RUTA_CONFIG
    cp = configparser.ConfigParser()
    cp["mysql"] = {
        "host": cfg.host,
        "port": str(cfg.port),
        "usuario": cfg.usuario,
        "password": cfg.password,
        "base": cfg.base,
    }
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        cp.write(f)
    try:
        os.chmod(ruta, 0o600)
    except OSError:
        pass
    return ruta
