"""Factura, alcance mínimo: datos fiscales del cliente y control de qué órdenes la pidieron y cuáles ya se
facturaron. El timbrado (CFDI) se hace fuera del sistema; aquí no se genera XML ni se habla con el SAT."""
from __future__ import annotations

import re
from datetime import date

from ..db import transaccion
from .comunes import ErrorNegocio, auditar, requerir_rol, texto

# Catálogo c_RegimenFiscal del SAT (CFDI 4.0).
REGIMENES = {
    "601": "General de Ley Personas Morales",
    "603": "Personas Morales con Fines no Lucrativos",
    "605": "Sueldos y Salarios e Ingresos Asimilados a Salarios",
    "606": "Arrendamiento",
    "607": "Régimen de Enajenación o Adquisición de Bienes",
    "608": "Demás ingresos",
    "610": "Residentes en el Extranjero sin Establecimiento Permanente en México",
    "611": "Ingresos por Dividendos (socios y accionistas)",
    "612": "Personas Físicas con Actividades Empresariales y Profesionales",
    "614": "Ingresos por intereses",
    "615": "Régimen de los ingresos por obtención de premios",
    "616": "Sin obligaciones fiscales",
    "620": "Sociedades Cooperativas de Producción que optan por diferir sus ingresos",
    "621": "Incorporación Fiscal",
    "622": "Actividades Agrícolas, Ganaderas, Silvícolas y Pesqueras",
    "623": "Opcional para Grupos de Sociedades",
    "624": "Coordinados",
    "625": "Actividades Empresariales con ingresos a través de Plataformas Tecnológicas",
    "626": "Régimen Simplificado de Confianza",
}

# Catálogo c_UsoCFDI del SAT (CFDI 4.0), sin CP01 (complemento de pago) ni CN01 (nómina):
# ninguno de los dos aplica a la factura de un servicio de lavandería.
USOS_CFDI = {
    "G01": "Adquisición de mercancías",
    "G02": "Devoluciones, descuentos o bonificaciones",
    "G03": "Gastos en general",
    "I01": "Construcciones",
    "I02": "Mobiliario y equipo de oficina por inversiones",
    "I03": "Equipo de transporte",
    "I04": "Equipo de cómputo y accesorios",
    "I05": "Dados, troqueles, moldes, matrices y herramental",
    "I06": "Comunicaciones telefónicas",
    "I07": "Comunicaciones satelitales",
    "I08": "Otra maquinaria y equipo",
    "D01": "Honorarios médicos, dentales y gastos hospitalarios",
    "D02": "Gastos médicos por incapacidad o discapacidad",
    "D03": "Gastos funerales",
    "D04": "Donativos",
    "D05": "Intereses reales pagados por créditos hipotecarios (casa habitación)",
    "D06": "Aportaciones voluntarias al SAR",
    "D07": "Primas por seguros de gastos médicos",
    "D08": "Gastos de transportación escolar obligatoria",
    "D09": "Depósitos en cuentas para el ahorro, primas con base en planes de pensiones",
    "D10": "Pagos por servicios educativos (colegiaturas)",
    "S01": "Sin efectos fiscales",
}

# 3 letras (persona moral) o 4 (persona física), fecha AAMMDD y homoclave de 3 (la última es dígito o A).
_RFC = re.compile(r"^([A-ZÑ&]{3,4})(\d{2})(\d{2})(\d{2})([A-Z\d]{2}[\dA])$")
_CP = re.compile(r"^\d{5}$")
CAMPOS_FISCALES = ("rfc", "razon_social", "regimen_fiscal", "uso_cfdi", "codigo_postal_fiscal")
NOMBRES_CAMPOS = {"rfc": "RFC", "razon_social": "razón social", "regimen_fiscal": "régimen fiscal",
                  "uso_cfdi": "uso del CFDI", "codigo_postal_fiscal": "código postal"}


def _fecha_valida(aa: int, mm: int, dd: int) -> bool:
    for siglo in (1900, 2000):  # el RFC no dice el siglo: basta que la fecha exista en alguno (29 de febrero)
        try:
            date(siglo + aa, mm, dd)
            return True
        except ValueError:
            pass
    return False


def normalizar_rfc(valor) -> str | None:
    """'aaa-010101 aa1' -> 'AAA010101AA1'. Lanza ErrorNegocio si el formato no es el de un RFC."""
    rfc = re.sub(r"[\s\-]", "", (valor or "")).upper()
    if not rfc:
        return None
    m = _RFC.match(rfc)
    if not m or not _fecha_valida(int(m.group(2)), int(m.group(3)), int(m.group(4))):
        raise ErrorNegocio("El RFC no tiene un formato válido: 12 caracteres para empresa (ej. ABC010203XY1) "
                           "o 13 para persona física (ej. ABCD010203XY1). Revísalo en la constancia fiscal.")
    return rfc


def validar_datos_fiscales(datos: dict) -> dict:
    """Valida y normaliza los campos fiscales presentes en `datos`. Todos son opcionales por separado:
    un cliente puede dar el RFC hoy y la constancia otro día; el reporte avisa qué falta."""
    v: dict = {}
    if "rfc" in datos:
        v["rfc"] = normalizar_rfc(datos["rfc"])
    if "razon_social" in datos:
        v["razon_social"] = texto(datos["razon_social"], "razón social", 254, False)
    if "regimen_fiscal" in datos:
        r = (datos["regimen_fiscal"] or "").strip() or None
        if r and r not in REGIMENES:
            raise ErrorNegocio("Elige el régimen fiscal de la lista (está en la constancia de situación fiscal).")
        v["regimen_fiscal"] = r
    if "uso_cfdi" in datos:
        u = (datos["uso_cfdi"] or "").strip().upper() or None
        if u and u not in USOS_CFDI:
            raise ErrorNegocio("Elige el uso del CFDI de la lista.")
        v["uso_cfdi"] = u
    if "codigo_postal_fiscal" in datos:
        cp = (datos["codigo_postal_fiscal"] or "").strip() or None
        if cp and not _CP.match(cp):
            raise ErrorNegocio("El código postal fiscal debe tener 5 dígitos.")
        v["codigo_postal_fiscal"] = cp
    return v


def faltantes(cliente: dict | None) -> list[str]:
    """Campos que le faltan al cliente para poder facturarle (el correo es opcional)."""
    if not cliente:
        return ["cliente"]
    return [NOMBRES_CAMPOS[c] for c in CAMPOS_FISCALES if not cliente.get(c)]


# ---------- Banderas de la orden ----------------------------------------------

def _orden(cur, orden_id: int) -> dict:
    cur.execute("SELECT id, folio, estado, cliente_id, requiere_factura, facturada, factura_folio FROM ordenes "
                "WHERE id = %s FOR UPDATE", (orden_id,))
    o = cur.fetchone()
    if not o:
        raise ErrorNegocio("Orden no encontrada.")
    return o


def marcar_requiere_factura(conn, sesion, orden_id: int, requiere: bool = True) -> None:
    """El empleado o la encargada indican que el cliente pidió (o ya no pide) factura."""
    requerir_rol(sesion, "administrador", "empleado")
    with transaccion(conn) as cur:
        o = _orden(cur, orden_id)
        if bool(o["requiere_factura"]) == bool(requiere):
            return
        if requiere:
            if o["estado"] == "cancelada":
                raise ErrorNegocio("La orden está cancelada: no se puede facturar.")
            if o["cliente_id"] is None:
                raise ErrorNegocio("Para facturar, la orden debe tener un cliente con sus datos fiscales. "
                                   "Las ventas de mostrador no se facturan.")
        elif o["facturada"]:
            raise ErrorNegocio("La orden ya está facturada. La encargada debe quitar primero la marca de facturada.")
        cur.execute("UPDATE ordenes SET requiere_factura = %s WHERE id = %s", (int(bool(requiere)), orden_id))
        auditar(cur, sesion, "factura_solicitada" if requiere else "factura_no_requerida", "ordenes", orden_id, o["folio"])


def marcar_facturada(conn, sesion, orden_id: int, folio_externo: str | None = None) -> None:
    """La encargada anota que ya emitió la factura (en su sistema de facturación), con el folio si lo tiene."""
    requerir_rol(sesion, "administrador")
    folio_externo = texto(folio_externo, "folio de la factura", 40, False)
    with transaccion(conn) as cur:
        o = _orden(cur, orden_id)
        if o["estado"] == "cancelada":
            raise ErrorNegocio("La orden está cancelada: no se puede marcar como facturada.")
        if o["cliente_id"] is None:
            raise ErrorNegocio("La orden no tiene cliente: asígnale uno antes de marcarla como facturada.")
        if o["facturada"]:
            raise ErrorNegocio(f"La orden ya está marcada como facturada"
                               + (f" (folio {o['factura_folio']})." if o["factura_folio"] else "."))
        cur.execute("UPDATE ordenes SET requiere_factura = 1, facturada = 1, factura_folio = %s, facturada_en = NOW(), "
                    "facturada_por = %s WHERE id = %s", (folio_externo, sesion["id"], orden_id))
        auditar(cur, sesion, "orden_facturada", "ordenes", orden_id,
                f"{o['folio']}" + (f" factura {folio_externo}" if folio_externo else ""))


def desmarcar_facturada(conn, sesion, orden_id: int, motivo: str) -> None:
    """Corrige una marca equivocada o una factura cancelada en el SAT. Solo la encargada y con motivo."""
    requerir_rol(sesion, "administrador")
    motivo = texto(motivo, "motivo", 200)
    with transaccion(conn) as cur:
        o = _orden(cur, orden_id)
        if not o["facturada"]:
            raise ErrorNegocio("La orden no está marcada como facturada.")
        cur.execute("UPDATE ordenes SET facturada = 0, factura_folio = NULL, facturada_en = NULL, facturada_por = NULL "
                    "WHERE id = %s", (orden_id,))
        auditar(cur, sesion, "orden_factura_quitada", "ordenes", orden_id,
                f"{o['folio']} (factura {o['factura_folio'] or 'sin folio'}): {motivo}")
