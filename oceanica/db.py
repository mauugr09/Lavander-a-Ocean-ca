"""Conexión a MySQL y migraciones versionadas."""
from __future__ import annotations

import hashlib
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import mysql.connector

from .config import CARPETA_MIGRACIONES, ConfigDB, cargar_config


def conectar(cfg: ConfigDB | None = None):
    cfg = cfg or cargar_config()
    conn = mysql.connector.connect(
        host=cfg.host,
        port=cfg.port,
        user=cfg.usuario,
        password=cfg.password,
        database=cfg.base,
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
        autocommit=False,
        sql_mode="STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION,ERROR_FOR_DIVISION_BY_ZERO",
        time_zone="SYSTEM",
        # En el ejecutable empaquetado se usa la implementación en Python del conector: la de C necesita
        # los plugins de autenticación del sistema (mysql_native_password.so/.dll), que no se incluyen.
        use_pure=bool(getattr(sys, "frozen", False)),
    )
    return conn


@contextmanager
def transaccion(conn) -> Iterator:
    """Cursor con commit si todo sale bien y rollback ante cualquier error."""
    cur = conn.cursor(dictionary=True)
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def dividir_sentencias(sql: str) -> list[str]:
    """Separa un script en sentencias respetando comillas y comentarios."""
    sentencias: list[str] = []
    actual: list[str] = []
    comilla: str | None = None
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if comilla:
            actual.append(c)
            if c == "\\" and i + 1 < n:
                actual.append(sql[i + 1])
                i += 1
            elif c == comilla:
                if i + 1 < n and sql[i + 1] == comilla:  # comilla escapada ''
                    actual.append(sql[i + 1])
                    i += 1
                else:
                    comilla = None
        elif c in ("'", '"', "`"):
            comilla = c
            actual.append(c)
        elif c == "-" and sql.startswith("--", i):
            fin = sql.find("\n", i)
            i = n if fin == -1 else fin
            continue
        elif c == ";":
            texto = "".join(actual).strip()
            if texto:
                sentencias.append(texto)
            actual = []
        else:
            actual.append(c)
        i += 1
    resto = "".join(actual).strip()
    if resto:
        sentencias.append(resto)
    return sentencias


_PATRON = re.compile(r"^(\d{3})_([a-z0-9_]+)\.sql$")


def listar_migraciones(carpeta: Path = CARPETA_MIGRACIONES) -> list[tuple[int, str, Path]]:
    encontradas = []
    for archivo in sorted(carpeta.glob("*.sql")):
        m = _PATRON.match(archivo.name)
        if m:
            encontradas.append((int(m.group(1)), m.group(2), archivo))
    return encontradas


def aplicar_migraciones(conn, carpeta: Path = CARPETA_MIGRACIONES) -> list[int]:
    """Aplica las migraciones pendientes en orden. Devuelve las versiones aplicadas.

    MySQL confirma automáticamente cada DDL, así que una migración que falla a la
    mitad no se puede revertir sola: no se marca como aplicada y debe corregirse
    (o restaurarse el respaldo) antes de reintentar.
    """
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS schema_migraciones (
             version INT UNSIGNED NOT NULL,
             nombre VARCHAR(80) NOT NULL,
             checksum CHAR(64) NOT NULL,
             aplicada_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
             PRIMARY KEY (version)
           ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    )
    cur.execute("SELECT version, checksum FROM schema_migraciones")
    hechas = {v: c for v, c in cur.fetchall()}
    aplicadas: list[int] = []
    for version, nombre, ruta in listar_migraciones(carpeta):
        texto = ruta.read_text(encoding="utf-8")
        checksum = hashlib.sha256(texto.encode("utf-8")).hexdigest()
        if version in hechas:
            if hechas[version] != checksum:
                raise RuntimeError(
                    f"La migración {ruta.name} cambió después de aplicarse. "
                    "Crea una migración nueva en lugar de editar una existente."
                )
            continue
        for sentencia in dividir_sentencias(texto):
            cur.execute(sentencia)
        cur.execute(
            "INSERT INTO schema_migraciones (version, nombre, checksum) VALUES (%s, %s, %s)",
            (version, nombre, checksum),
        )
        conn.commit()
        aplicadas.append(version)
    cur.close()
    return aplicadas


def siguiente_folio(cur, prefijo: str) -> str:
    """Folio consecutivo tipo OC-000123. Debe llamarse dentro de la transacción
    que inserta la orden; el bloqueo FOR UPDATE evita folios repetidos."""
    cur.execute(
        "SELECT folio FROM ordenes WHERE folio LIKE %s ORDER BY id DESC LIMIT 1 FOR UPDATE",
        (prefijo + "-%",),
    )
    fila = cur.fetchone()
    if not fila:
        numero = 1
    else:
        folio = fila["folio"] if isinstance(fila, dict) else fila[0]
        numero = int(folio.rsplit("-", 1)[1]) + 1
    return f"{prefijo}-{numero:06d}"
