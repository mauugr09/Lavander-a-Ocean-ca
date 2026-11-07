"""Utilidades compartidas por los servicios de negocio."""
from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from ..seguridad import ErrorAcceso, registrar_auditoria  # noqa: F401  (re-export)

CENTAVO = Decimal("0.01")
CERO = Decimal("0.00")


class ErrorNegocio(Exception):
    """Regla de negocio incumplida; el mensaje se puede mostrar al usuario."""


def dinero(valor, campo: str = "monto") -> Decimal:
    try:
        d = Decimal(str(valor)).quantize(CENTAVO, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise ErrorNegocio(f"El campo '{campo}' no es un número válido.")
    return d


def cantidad(valor, campo: str = "cantidad") -> Decimal:
    d = dinero(valor, campo)
    if d <= 0:
        raise ErrorNegocio(f"El campo '{campo}' debe ser mayor que cero.")
    return d


def texto(valor, campo: str, maximo: int, obligatorio: bool = True) -> str | None:
    v = (valor or "").strip()
    if not v:
        if obligatorio:
            raise ErrorNegocio(f"El campo '{campo}' es obligatorio.")
        return None
    if len(v) > maximo:
        raise ErrorNegocio(f"El campo '{campo}' admite máximo {maximo} caracteres.")
    return v


def como_fecha(valor, campo: str = "fecha") -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor).strip())
    except ValueError:
        raise ErrorNegocio(f"El campo '{campo}' debe tener formato AAAA-MM-DD.")


def requerir_rol(sesion: dict, *roles: str) -> None:
    if not sesion or sesion.get("rol") not in roles:
        raise ErrorAcceso("No tienes permiso para esta acción.")


def es_admin(sesion: dict) -> bool:
    return bool(sesion) and sesion.get("rol") == "administrador"


def config_valor(cur, clave: str, defecto: str = "") -> str:
    cur.execute("SELECT valor FROM configuracion WHERE clave = %s", (clave,))
    fila = cur.fetchone()
    if not fila:
        return defecto
    return fila["valor"] if isinstance(fila, dict) else fila[0]


def config_si(cur, clave: str, defecto: bool = False) -> bool:
    return config_valor(cur, clave, "si" if defecto else "no").strip().lower() in ("si", "sí", "1", "true", "yes")


def auditar(cur, sesion, accion, tabla=None, registro_id=None, detalle=None):
    registrar_auditoria(cur, sesion.get("id") if sesion else None, accion, tabla, registro_id, detalle)


def escapar_like(valor: str) -> str:
    return valor.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
