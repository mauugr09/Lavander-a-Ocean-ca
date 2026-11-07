"""Lectura y edición de la configuración del negocio."""
from __future__ import annotations

from ..db import transaccion
from .comunes import ErrorNegocio, auditar, requerir_rol, texto

# Claves cuyo valor debe ser numérico (validación al editar).
_NUMERICAS = {
    "dias_entrega_default", "hora_entrada_tolerancia_min", "respaldo_retencion_dias",
    "descuento_max_pct_empleado", "nomina_jornada_horas", "nomina_factor_hora_extra", "ticket_ancho",
    "nomina_salario_minimo_diario", "nomina_pago_hora_extra",
}
_SI_NO = {"entrega_requiere_pago_total", "asistencia_paga_justificada", "horas_extra_automaticas"}
_OPCIONES = {"entrega_transferencia_pendiente": ("no", "admin", "todos")}


def obtener_todo(conn) -> dict[str, str]:
    with transaccion(conn) as cur:
        cur.execute("SELECT clave, valor FROM configuracion ORDER BY clave")
        return {f["clave"]: f["valor"] for f in cur.fetchall()}


def listar(conn) -> list[dict]:
    """Claves con su valor y descripción, para la pantalla de configuración."""
    with transaccion(conn) as cur:
        cur.execute("SELECT clave, valor, descripcion FROM configuracion ORDER BY clave")
        return cur.fetchall()


def obtener(conn, clave: str, defecto: str = "") -> str:
    with transaccion(conn) as cur:
        cur.execute("SELECT valor FROM configuracion WHERE clave = %s", (clave,))
        fila = cur.fetchone()
        return fila["valor"] if fila else defecto


def establecer(conn, sesion, clave: str, valor: str) -> None:
    requerir_rol(sesion, "administrador")
    valor = texto(valor, clave, 255, obligatorio=clave in _NUMERICAS or clave in _SI_NO or clave in _OPCIONES) or ""
    if clave in _NUMERICAS:
        try:
            if float(valor) < 0:
                raise ValueError
        except ValueError:
            raise ErrorNegocio(f"'{clave}' debe ser un número mayor o igual a cero.")
    if clave in _SI_NO and valor.lower() not in ("si", "no"):
        raise ErrorNegocio(f"'{clave}' solo admite 'si' o 'no'.")
    if clave in _OPCIONES and valor not in _OPCIONES[clave]:
        raise ErrorNegocio(f"'{clave}' solo admite: {', '.join(_OPCIONES[clave])}.")
    if clave == "respaldo_hora":
        try:
            h, m = valor.split(":")
            if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
                raise ValueError
        except ValueError:
            raise ErrorNegocio("La hora de respaldo debe tener formato HH:MM.")
    with transaccion(conn) as cur:
        cur.execute("SELECT valor FROM configuracion WHERE clave = %s FOR UPDATE", (clave,))
        anterior = cur.fetchone()
        if not anterior:
            raise ErrorNegocio(f"La configuración '{clave}' no existe.")
        cur.execute("UPDATE configuracion SET valor = %s WHERE clave = %s", (valor, clave))
        auditar(cur, sesion, "configuracion_cambiada", "configuracion", None,
                f"{clave}: '{anterior['valor']}' -> '{valor}'")
