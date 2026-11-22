"""Respaldo y restauración de la base de datos con mysqldump / mysql.

Uso desde línea de comandos (el programador de tareas de Windows llama al
automático todos los días):
    python -m oceanica.respaldos --auto
    python -m oceanica.respaldos --manual
    python -m oceanica.respaldos --restaurar ARCHIVO.sql.gz
"""
from __future__ import annotations

import argparse
import gzip
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from .config import CARPETA_RESPALDOS, ConfigDB, cargar_config
from .db import conectar


@contextmanager
def _archivo_credenciales(cfg: ConfigDB):
    """Archivo temporal para que la contraseña no aparezca en la lista de procesos."""
    fd, ruta = tempfile.mkstemp(suffix=".cnf")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"[client]\nuser={cfg.usuario}\npassword=\"{cfg.password}\"\n"
                    f"host={cfg.host}\nport={cfg.port}\n")
        yield ruta
    finally:
        try:
            os.remove(ruta)
        except OSError:
            pass


def _carpetas_bin_conocidas() -> list[Path]:
    """Carpetas `bin` donde los instaladores de MariaDB y MySQL dejan sus programas (la más nueva primero)."""
    carpetas: list[Path] = []
    for base in {os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"), os.environ.get("ProgramFiles(x86)")}:
        if not base:
            continue
        for patron in ("MariaDB */bin", "MySQL/MySQL Server */bin"):
            carpetas.extend(Path(base).glob(patron))
    def version(c: Path) -> tuple:   # «MariaDB 10.11» va antes que «MariaDB 10.3»
        return tuple(int(n) for n in re.findall(r"\d+", c.parent.name))
    return sorted(carpetas, key=version, reverse=True)


def _buscar(programa: str) -> str:
    ruta = shutil.which(programa)
    if ruta:
        return ruta
    # Sin PATH: el instalador de Oceánica no lo modifica, así que se busca donde lo deja MariaDB/MySQL.
    for carpeta in _carpetas_bin_conocidas():
        for nombre in (f"{programa}.exe", programa):
            if (carpeta / nombre).is_file():
                return str(carpeta / nombre)
    raise FileNotFoundError(
        f"No se encontró '{programa}'. Revise que MariaDB esté instalado en esta computadora."
    )


def crear_respaldo(tipo: str = "manual", usuario_id: int | None = None,
                   cfg: ConfigDB | None = None, carpeta: Path = CARPETA_RESPALDOS) -> Path:
    cfg = cfg or cargar_config()
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"oceanica_{datetime.now():%Y%m%d_%H%M%S}_{tipo}.sql.gz"
    mysqldump = _buscar("mysqldump")
    with _archivo_credenciales(cfg) as cnf:
        cmd = [mysqldump, f"--defaults-extra-file={cnf}", "--single-transaction",
               "--routines", "--default-character-set=utf8mb4", cfg.base]
        with gzip.open(destino, "wb") as salida:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode != 0:
                salida.close()
                destino.unlink(missing_ok=True)
                raise RuntimeError("mysqldump falló: " + proc.stderr.decode("utf-8", "replace")[:300])
            salida.write(proc.stdout)

    externo = _copiar_a_externo(destino, cfg)
    _registrar(destino, tipo, usuario_id, externo, cfg)
    _limpiar_antiguos(carpeta, cfg)
    return destino


def _leer_config(cfg: ConfigDB, clave: str, defecto: str = "") -> str:
    conn = conectar(cfg)
    try:
        cur = conn.cursor()
        cur.execute("SELECT valor FROM configuracion WHERE clave = %s", (clave,))
        fila = cur.fetchone()
        return fila[0] if fila else defecto
    finally:
        conn.close()


def _copiar_a_externo(archivo: Path, cfg: ConfigDB) -> bool:
    ruta = _leer_config(cfg, "respaldo_ruta_externa")
    if not ruta:
        return False
    carpeta = Path(ruta)
    if not carpeta.is_dir():  # disco desconectado: no es error fatal
        return False
    shutil.copy2(archivo, carpeta / archivo.name)
    return True


def _registrar(archivo: Path, tipo: str, usuario_id, externo: bool, cfg: ConfigDB) -> None:
    conn = conectar(cfg)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO respaldos (archivo, tamano_bytes, tipo, usuario_id, copiado_a_externo) "
            "VALUES (%s, %s, %s, %s, %s)",
            (archivo.name, archivo.stat().st_size, tipo, usuario_id, int(externo)),
        )
        conn.commit()
    finally:
        conn.close()


def _limpiar_antiguos(carpeta: Path, cfg: ConfigDB) -> None:
    dias = int(_leer_config(cfg, "respaldo_retencion_dias", "30") or 30)
    limite = datetime.now() - timedelta(days=dias)
    for f in carpeta.glob("oceanica_*.sql.gz"):
        if datetime.fromtimestamp(f.stat().st_mtime) < limite:
            f.unlink(missing_ok=True)


def restaurar(archivo: Path, cfg: ConfigDB | None = None) -> None:
    """Restaura un respaldo SOBRE la base actual. Reemplaza los datos existentes."""
    cfg = cfg or cargar_config()
    if not archivo.exists():
        raise FileNotFoundError(archivo)
    mysql = _buscar("mysql")
    with _archivo_credenciales(cfg) as cnf:
        cmd = [mysql, f"--defaults-extra-file={cnf}", "--default-character-set=utf8mb4", cfg.base]
        with gzip.open(archivo, "rb") as entrada:
            proc = subprocess.run(cmd, input=entrada.read(), stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError("La restauración falló: " + proc.stderr.decode("utf-8", "replace")[:300])


def estado(conn, ahora: datetime | None = None, carpeta: Path = CARPETA_RESPALDOS) -> dict:
    """Qué tan protegido está el negocio hoy, para avisarle al administrador.

    Devuelve {'nivel': 'ok' | 'aviso' | 'alerta', 'mensaje', 'ultimo': datetime | None, 'dias': int | None}.
    alerta: nunca se ha respaldado, el último tiene más de un día, o su archivo ya no está en la carpeta.
    aviso: hay respaldo reciente pero no se copió al disco externo (si la laptop falla, se pierde con ella)."""
    ahora = ahora or datetime.now()
    cur = conn.cursor()
    try:
        cur.execute("SELECT archivo, creado_en, copiado_a_externo FROM respaldos ORDER BY creado_en DESC, id DESC LIMIT 1")
        fila = cur.fetchone()
    finally:
        cur.close()
        conn.commit()
    if not fila:
        return {"nivel": "alerta", "mensaje": "Nunca se ha hecho un respaldo", "ultimo": None, "dias": None}
    archivo, creado, externo = (fila["archivo"], fila["creado_en"], fila["copiado_a_externo"]) if isinstance(fila, dict) else fila
    dias = max(0, (ahora.date() - creado.date()).days)
    hace = "hoy" if dias == 0 else ("ayer" if dias == 1 else f"hace {dias} días")
    base = {"ultimo": creado, "dias": dias}
    if ahora - creado > timedelta(hours=36):
        return {**base, "nivel": "alerta", "mensaje": f"Último respaldo: {hace}"}
    if not (carpeta / archivo).exists():
        return {**base, "nivel": "alerta", "mensaje": f"El respaldo de {hace} ya no está en la carpeta"}
    if not externo:
        return {**base, "nivel": "aviso", "mensaje": f"Respaldo de {hace}, sin copia en disco externo"}
    return {**base, "nivel": "ok", "mensaje": f"Respaldo de {hace}, con copia externa"}


def main() -> None:
    p = argparse.ArgumentParser(description="Respaldos de Oceánica Gestión")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--auto", action="store_true")
    g.add_argument("--manual", action="store_true")
    g.add_argument("--restaurar", metavar="ARCHIVO")
    a = p.parse_args()
    if a.restaurar:
        if input("Esto reemplaza los datos actuales. Escribe SI para continuar: ").strip() != "SI":
            print("Cancelado.")
            return
        restaurar(Path(a.restaurar))
        print("Restauración completada.")
    else:
        print("Respaldo creado:", crear_respaldo("automatico" if a.auto else "manual"))


if __name__ == "__main__":
    main()
