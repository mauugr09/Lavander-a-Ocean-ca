"""Programa (o quita) el respaldo diario en el Programador de tareas de Windows:

    OceanicaAdmin.exe programar-respaldo            (el instalador lo corre solo)
    OceanicaAdmin.exe programar-respaldo --quitar

La tarea corre con la cuenta de Windows de quien la crea (ahí está la configuración del sistema) y solo mientras esa
cuenta tiene la sesión abierta, así que no guarda ninguna contraseña. Si la computadora estaba apagada a la hora del
respaldo (la lavandería cierra antes de las 21:00), Windows lo hace en cuanto vuelve a encenderse.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

NOMBRE_TAREA = r"\Oceanica\Respaldo diario"
HORA_POR_OMISION = "21:00"
_HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def comando_respaldo() -> tuple[str, str]:
    """(programa, argumentos) que hacen el respaldo automático, empaquetado o no."""
    if getattr(sys, "frozen", False):
        ejecutable = Path(sys.executable)
        admin = ejecutable.with_name("OceanicaAdmin.exe")  # la versión con consola, aunque se llame desde Oceanica.exe
        return str(admin if admin.exists() else ejecutable), "respaldo --auto"
    return sys.executable, "-m oceanica.respaldos --auto"


def hora_configurada() -> str:
    """La hora de `respaldo_hora` en la configuración; si no hay base o no es válida, 21:00."""
    try:
        from .config import cargar_config
        from .db import conectar
        conn = conectar(cargar_config())
        try:
            cur = conn.cursor()
            cur.execute("SELECT valor FROM configuracion WHERE clave = 'respaldo_hora'")
            fila = cur.fetchone()
        finally:
            conn.close()
        valor = (fila[0] if fila else "").strip()
        return valor if _HORA.match(valor) else HORA_POR_OMISION
    except Exception:  # noqa: BLE001 — sin base todavía (instalación nueva): se usa la hora por omisión
        return HORA_POR_OMISION


def xml_tarea(programa: str, argumentos: str, hora: str, hoy: date | None = None) -> str:
    """Definición de la tarea (formato del Programador de tareas)."""
    if not _HORA.match(hora):
        raise ValueError(f"Hora no válida: {hora!r} (use HH:MM, por ejemplo 21:00)")
    inicio = f"{(hoy or date.today()).isoformat()}T{hora}:00"
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Respaldo diario de la base de datos de Lavandería Oceánica.</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{inicio}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(programa)}</Command>
      <Arguments>{escape(argumentos)}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def programar(hora: str | None = None) -> str:
    """Crea o reemplaza la tarea. Devuelve la hora programada."""
    hora = hora or hora_configurada()
    programa, argumentos = comando_respaldo()
    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / "tarea.xml"
        ruta.write_text(xml_tarea(programa, argumentos, hora), encoding="utf-16")  # schtasks lee UTF-16
        r = subprocess.run(["schtasks", "/Create", "/F", "/TN", NOMBRE_TAREA, "/XML", str(ruta)],
                           capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or f"schtasks terminó con código {r.returncode}")
    return hora


def quitar() -> None:
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", NOMBRE_TAREA], capture_output=True, text=True)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if sys.platform != "win32":
        print("El respaldo programado solo se configura en Windows.")
        return 1
    if "--quitar" in argv:
        quitar()
        print("Se quitó el respaldo diario del Programador de tareas.")
        return 0
    try:
        hora = programar()
    except Exception as e:  # noqa: BLE001 — lo lee quien instala
        print(f"No se pudo programar el respaldo diario: {e}\n"
              "Prográmelo a mano en el Programador de tareas: OceanicaAdmin.exe respaldo --auto")
        return 1
    print(f"Respaldo diario programado a las {hora} (si la computadora está apagada, se hace al encenderla).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
