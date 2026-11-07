"""Tickets de orden y de corte, recibo de nómina e impresión en Windows."""
from __future__ import annotations

import logging
import textwrap
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import caja, configuracion, nomina, ordenes
from .comunes import ErrorNegocio, requerir_rol
from .exportacion import formatear


log = logging.getLogger("oceanica")


class ErrorImpresion(Exception):
    """No se pudo imprimir; el mensaje indica qué revisar (sin texto técnico: ese va al registro)."""


# ---------- Formato de texto de ancho fijo -----------------------------------

def _ancho(conn) -> int:
    try:
        return max(24, min(64, int(configuracion.obtener(conn, "ticket_ancho", "42"))))
    except ValueError:
        return 42


def _centrado(texto: str, ancho: int) -> list[str]:
    return [l.center(ancho).rstrip() for l in textwrap.wrap(texto, ancho)] if texto else []


def _par(izq: str, der: str, ancho: int) -> str:
    espacio = ancho - len(izq) - len(der)
    if espacio < 1:
        izq = izq[: max(0, ancho - len(der) - 1)]
        espacio = max(1, ancho - len(izq) - len(der))
    return izq + " " * espacio + der


def _dinero(valor) -> str:
    return f"{Decimal(valor):,.2f}"


def _fecha(valor) -> str:
    return valor.strftime("%d/%m/%Y %H:%M") if valor else ""


def _encabezado(conn, ancho: int) -> list[str]:
    cfg = configuracion.obtener_todo(conn)
    lineas = _centrado(cfg.get("negocio_nombre", ""), ancho)
    lineas += _centrado(cfg.get("negocio_direccion", ""), ancho)
    if cfg.get("negocio_telefono"):
        lineas += _centrado("Tel: " + cfg["negocio_telefono"], ancho)
    return lineas


def ticket_orden_texto(conn, orden_id: int) -> str:
    ancho = _ancho(conn)
    o = ordenes.obtener_orden(conn, orden_id)
    pie = configuracion.obtener(conn, "ticket_pie", "")
    sep = "-" * ancho
    cliente = " ".join(filter(None, [o["cliente"]["nombre"], o["cliente"]["apellidos"]])) if o["cliente"] else "Mostrador"
    L = _encabezado(conn, ancho) + [sep, f"Folio: {o['folio']}", f"Fecha: {_fecha(o['fecha_recepcion'])}",
                                    f"Cliente: {cliente}"]
    if o["cliente"] and o["cliente"]["telefono"]:
        L.append(f"Tel. cliente: {o['cliente']['telefono']}")
    L += [f"Atendió: {o['recibio']}", sep]
    for d in o["detalle"]:
        cant = Decimal(d["cantidad"])
        cant_txt = f"{cant:g} kg" if d["unidad"] == "kilo" else f"{int(cant)} pz"
        nombre = d["servicio"] + (f" ({d['descripcion']})" if d["descripcion"] else "")
        L.append(_par(f"{cant_txt} {nombre}"[: ancho - 10], _dinero(d["importe"]), ancho))
        L.append(f"   a ${_dinero(d['precio_unitario'])} c/u")
    L.append(sep)
    L.append(_par("Subtotal", _dinero(o["subtotal"]), ancho))
    if Decimal(o["descuento"]) > 0:
        L.append(_par("Descuento", "-" + _dinero(o["descuento"]), ancho))
    L.append(_par("TOTAL", _dinero(o["total"]), ancho))
    for p in o["pagos"]:
        signo = "-" if p["tipo"] == "reembolso" else ""
        marca = {"pendiente": " POR CONFIRMAR", "rechazado": " RECHAZADO"}.get(p["estado_confirmacion"], "")
        L.append(_par(f"{p['tipo'].capitalize()} ({p['metodo']}){marca}", signo + _dinero(p["monto"]), ancho))
    L.append(_par("SALDO PENDIENTE", _dinero(o["saldo"]), ancho))
    L += [sep, f"Entrega: {_fecha(o['fecha_promesa'])}"]
    if o["facturada"]:
        L.append("Factura: emitida" + (f" ({o['factura_folio']})" if o["factura_folio"] else ""))
    elif o["requiere_factura"]:
        L.append("Factura: solicitada")
    if o["observaciones"]:
        L += textwrap.wrap("Nota: " + o["observaciones"], ancho)
    if o["estado"] == "cancelada":
        L += ["", *_centrado("*** ORDEN CANCELADA ***", ancho)]
    if pie:
        L += ["", *_centrado(pie, ancho)]
    return "\n".join(L) + "\n"


def ticket_corte_texto(conn, corte_id: int) -> str:
    ancho = _ancho(conn)
    r = caja.resumen_corte(conn, corte_id)
    c = r["corte"]
    sep = "-" * ancho
    L = _encabezado(conn, ancho) + [sep, *_centrado(f"CORTE DE CAJA #{c['id']}", ancho),
                                    f"Apertura: {_fecha(c['abierta_en'])}", f"Cierre:   {_fecha(c['cerrada_en']) or 'abierto'}", sep,
                                    _par("Fondo inicial", _dinero(c["fondo_inicial"]), ancho)]
    for m in r["por_metodo"]:
        L.append(_par(f"Cobrado {m['metodo']}", _dinero(m["total"]), ancho))
    if r["transferencias_pendientes"]["cantidad"]:
        L.append(_par(f"Transf. por confirmar ({r['transferencias_pendientes']['cantidad']})",
                      _dinero(r["transferencias_pendientes"]["total"]), ancho))
    L += [_par("Ingresos", _dinero(r["ingresos"]), ancho), _par("Gastos", "-" + _dinero(r["gastos"]), ancho),
          _par("Retiros", "-" + _dinero(r["retiros"]), ancho), sep,
          _par("EFECTIVO ESPERADO", _dinero(r["efectivo_esperado"]), ancho)]
    if c["efectivo_contado"] is not None:
        L += [_par("Efectivo contado", _dinero(c["efectivo_contado"]), ancho),
              _par("DIFERENCIA", _dinero(c["diferencia"]), ancho)]
    if c["observaciones"]:
        L += textwrap.wrap("Obs: " + c["observaciones"], ancho)
    return "\n".join(L) + "\n"


# ---------- PDF de ticket (vista previa o impresora no térmica) --------------

def texto_a_pdf_ticket(texto: str, ruta) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    lineas = texto.rstrip("\n").split("\n")
    alto = len(lineas) * 10 + 24
    c = canvas.Canvas(str(ruta), pagesize=(80 * mm, alto))
    c.setFont("Courier", 8)
    y = alto - 14
    for l in lineas:
        c.drawString(8, y, l)
        y -= 10
    c.save()
    return ruta


def ticket_orden_pdf(conn, orden_id: int, ruta) -> Path:
    return texto_a_pdf_ticket(ticket_orden_texto(conn, orden_id), ruta)


# ---------- Impresión directa en Windows -------------------------------------

def listar_impresoras() -> list[str]:
    try:
        import win32print
    except ImportError:
        raise ErrorImpresion("La lista de impresoras requiere Windows y el paquete pywin32 (pip install pywin32).")
    return [p[2] for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)]


def imprimir_texto(texto: str, impresora: str | None = None) -> None:
    """Envía el ticket en modo RAW a una impresora térmica ESC/POS (código de página 850) y corta el papel."""
    try:
        import win32print
    except ImportError:
        log.warning("Impresión directa no disponible: falta pywin32 (o no es Windows)")
        raise ErrorImpresion("Esta computadora no puede imprimir directo en la impresora de tickets. "
                             "Puedes abrir el PDF del ticket e imprimirlo desde ahí.")
    try:
        nombre = impresora or win32print.GetDefaultPrinter()
        datos = b"\x1b@" + b"\x1bt\x02" + texto.encode("cp850", errors="replace") + b"\n\n\n\n" + b"\x1dV\x42\x00"
        h = win32print.OpenPrinter(nombre)
        try:
            win32print.StartDocPrinter(h, 1, ("Ticket", None, "RAW"))
            try:
                win32print.StartPagePrinter(h)
                win32print.WritePrinter(h, datos)
                win32print.EndPagePrinter(h)
            finally:
                win32print.EndDocPrinter(h)
        finally:
            win32print.ClosePrinter(h)
    except Exception as e:  # pywintypes.error u otros del controlador
        log.exception("Falló la impresión del ticket en %r", impresora)
        raise ErrorImpresion(f"No se pudo imprimir en «{impresora or 'la impresora predeterminada'}». Revisa que esté "
                             "encendida, conectada y con papel. Si sigue igual, avisa a la encargada.") from e


def imprimir_ticket_orden(conn, orden_id: int) -> None:
    imprimir_texto(ticket_orden_texto(conn, orden_id), configuracion.obtener(conn, "impresora_ticket", "") or None)


# ---------- Recibo de pago de nómina (control interno) -----------------------

def recibo_nomina_pdf(conn, sesion, nomina_empleado_id: int, ruta) -> Path:
    requerir_rol(sesion, "administrador")
    datos = nomina.datos_recibo(conn, sesion, nomina_empleado_id)
    p, n = datos["periodo"], datos["nomina"]
    negocio = configuracion.obtener(conn, "negocio_nombre", "")
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    est = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(ruta), pagesize=LETTER, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm, title="Recibo de pago")
    E = [Paragraph(negocio or "&nbsp;", est["Title"]), Paragraph("Recibo de pago (control interno)", est["Heading2"]),
         Paragraph(f"Empleado: <b>{n['empleado']}</b>" + (f" - {n['puesto']}" if n["puesto"] else ""), est["Normal"]),
         Paragraph(f"Periodo {p['periodicidad']}: {formatear(p['fecha_inicio'], 'fecha')} al {formatear(p['fecha_fin'], 'fecha')}", est["Normal"]),
         Paragraph(f"Días pagados: {formatear(n['dias_trabajados'], 'numero')} &nbsp; Horas trabajadas: {formatear(n['horas_trabajadas'], 'numero')}", est["Normal"]),
         *([Paragraph(f"Forma de pago: {n['metodo_pago']}", est["Normal"])] if n.get("metodo_pago") else []),
         Spacer(1, 0.5 * cm)]
    filas = [["Concepto", "Detalle", "Percepción", "Deducción"]]
    for d in n["detalle"]:
        es_p = d["tipo"] == "percepcion"
        filas.append([d["concepto"], d["descripcion"] or "", formatear(d["monto"], "dinero") if es_p else "",
                      "" if es_p else formatear(d["monto"], "dinero")])
    filas.append(["TOTALES", "", formatear(n["total_percepciones"], "dinero"), formatear(n["total_deducciones"], "dinero")])
    filas.append(["NETO A PAGAR", "", "", formatear(n["neto"], "dinero")])
    t = Table(filas, colWidths=[4.5 * cm, 6 * cm, 3 * cm, 3 * cm], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 9),
                           ("ALIGN", (2, 1), (3, -1), "RIGHT"), ("FONTNAME", (0, -2), (-1, -1), "Helvetica-Bold")]))
    E += [t, Spacer(1, 2.5 * cm), Paragraph("_______________________________<br/>Firma del empleado (recibí conforme)", est["Normal"]),
          Spacer(1, 0.8 * cm),
          Paragraph("Este recibo es un comprobante interno de pago. No es un CFDI de nómina ni sustituye "
                    "obligaciones fiscales o de seguridad social.", est["Italic"])]
    doc.build(E)
    return ruta
