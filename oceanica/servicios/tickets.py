"""Tickets de orden y de corte, recibo de nómina e impresión en Windows."""
from __future__ import annotations

import logging
import re
import textwrap
from decimal import Decimal
from pathlib import Path

from reportlab.graphics.barcode import code128
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..config import CARPETA_PROGRAMA
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


def _titulo(texto: str, ancho: int) -> list[str]:
    return ["=" * ancho, *_centrado(texto, ancho), "=" * ancho]



def _columnas_detalle(ancho: int) -> tuple[int, int, int, int, int]:
    """Anchos de Cant, Servicio, P.U., Ud e Importe que suman el ancho del papel (con 4 espacios)."""
    cant, pu, ud, imp = 4, 8, 3, 10
    if ancho < 40:  # papel de 58 mm
        pu, imp = 7, 8
    return cant, ancho - cant - pu - ud - imp - 4, pu, ud, imp


def ticket_orden_texto(conn, orden_id: int) -> str:
    ancho = _ancho(conn)
    o = ordenes.obtener_orden(conn, orden_id)
    cfg = configuracion.obtener_todo(conn)
    sep = "-" * ancho
    cliente = " ".join(filter(None, [o["cliente"]["nombre"], o["cliente"]["apellidos"]])) if o["cliente"] else "Mostrador"
    numero = o["folio"].rsplit("-", 1)[-1].lstrip("0") or "0"

    L = _encabezado(conn, ancho)
    L += ["", *_titulo("DATOS DEL CLIENTE", ancho)]
    L += textwrap.wrap(f"Nombre: {cliente}", ancho)
    if o["cliente"] and o["cliente"]["telefono"]:
        L.append(f"Teléfono: {o['cliente']['telefono']}")
    ancho_etq = 17 if ancho >= 40 else 11
    L += [f"{'Fecha recepción:' if ancho >= 40 else 'Recepción:':<{ancho_etq}}{_fecha(o['fecha_recepcion'])}",
          f"{'Fecha entrega:' if ancho >= 40 else 'Entrega:':<{ancho_etq}}{_fecha(o['fecha_promesa'])}"]
    if o.get("tipo_entrega") == "domicilio":
        L += ["SERVICIO A DOMICILIO", *textwrap.wrap("Dirección: " + (o["direccion_entrega"] or ""), ancho)]
    else:
        L.append("Recoge en mostrador")
    L.append(f"Atendió: {o['recibio']}")

    L += ["", *_titulo(f"DETALLES DE LA ORDEN #{numero}", ancho), f"Folio: {o['folio']}"]
    c_cant, c_serv, c_pu, c_ud, c_imp = _columnas_detalle(ancho)

    def fila(cant, serv, pu, ud, imp):
        return (f"{cant:<{c_cant}} {serv[:c_serv]:<{c_serv}} {pu:>{c_pu}} {ud:<{c_ud}} {imp:>{c_imp}}").rstrip()

    L += [fila("Cant", "Servicio", "P.U.", "Ud", "Importe"), sep]
    for d in o["detalle"]:
        cant = Decimal(d["cantidad"])
        cant_txt = format(cant.normalize(), "f") if d["unidad"] == "kilo" else f"{int(cant)}"
        nombre = (d["servicio"] + (f" ({d['descripcion']})" if d["descripcion"] else "")).upper()
        partes = textwrap.wrap(nombre, c_serv) or [""]
        L.append(fila(cant_txt, partes[0], "$" + _dinero(d["precio_unitario"]), "kg" if d["unidad"] == "kilo" else "pz",
                      "$" + _dinero(d["importe"])))
        L += [fila("", p, "", "", "") for p in partes[1:]]
    L.append(sep)
    L.append(_par("Total productos:", "$" + _dinero(o["subtotal"]), ancho))
    if Decimal(o["descuento"]) > 0:
        L.append(_par("Descuento:", "-$" + _dinero(o["descuento"]), ancho))
    if o.get("tipo_entrega") == "domicilio":
        L.append(_par("Servicio a domicilio:", "$" + _dinero(o["cargo_domicilio"]), ancho))
    L.append(_par("TOTAL:", "$" + _dinero(o["total"]), ancho))
    L.append("")
    if not o["pagos"]:
        L.append(_par("Anticipo:", "$0.00", ancho))
    for p in o["pagos"]:
        signo = "-" if p["tipo"] == "reembolso" else ""
        marca = {"pendiente": " POR CONFIRMAR", "rechazado": " RECHAZADO"}.get(p["estado_confirmacion"], "")
        L.append(_par(f"{p['tipo'].capitalize()} ({p['metodo']}):", signo + "$" + _dinero(p["monto"]), ancho))
        if marca:
            L.append("  " + marca.strip())
    L.append(_par("POR LIQUIDAR:", "$" + _dinero(o["saldo"]), ancho))
    if o["facturada"]:
        L.append("Factura: emitida" + (f" ({o['factura_folio']})" if o["factura_folio"] else ""))
    elif o["requiere_factura"]:
        L.append("Factura: solicitada")
    if o["observaciones"]:
        L += ["", *textwrap.wrap("Nota: " + o["observaciones"], ancho)]
    if o["estado"] == "cancelada":
        L += ["", *_centrado("*** ORDEN CANCELADA ***", ancho)]

    condiciones = [c.strip() for c in (cfg.get("ticket_condiciones") or "").replace("\\n", "\n").split("\n") if c.strip()]
    if condiciones:
        L += ["", *_titulo("CONDICIONES DEL SERVICIO", ancho)]
        for c in condiciones:
            L += textwrap.wrap("* " + c, ancho, subsequent_indent="  ")
    almacenaje = (cfg.get("ticket_almacenaje") or "").strip()
    if almacenaje:
        L += ["", *_titulo("ALMACENAJE", ancho), *textwrap.wrap(almacenaje, ancho)]
    linea = "_" * max(ancho - 12, 10)
    L += ["", f"Anticipo:  {linea}", f"Saldo:     {linea}", f"Firma:     {linea}", ""]
    if codigo_barras_activo(conn):
        L += [marca_codigo(o["folio"]), ""]
    L.append("=" * ancho)
    pie = (cfg.get("ticket_pie") or "").strip()
    if pie:
        L += _centrado(f"***{pie.upper()}***" if len(pie) + 6 <= ancho else pie.upper(), ancho)
    if cfg.get("negocio_web"):
        L += _centrado(cfg["negocio_web"], ancho)
    ajustadas = []  # ningún renglón puede pasarse del ancho del papel
    for l in L:
        ajustadas += textwrap.wrap(l, ancho) if len(l) > ancho else [l]
    return "\n".join(ajustadas) + "\n"


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


def etiquetas_bolsa_texto(conn, orden_id: int, bolsas: int) -> str:
    """Una etiqueta por bolsa o paquete de la orden, para pegarla y no confundir la ropa de dos clientes.
    Folio, cliente, «bolsa 1 de 3» y fecha de entrega; con el código de barras activo, también el folio en barras."""
    try:
        bolsas = int(bolsas)
    except (TypeError, ValueError):
        raise ErrorNegocio("Escriba cuántas bolsas son.")
    if not 1 <= bolsas <= 30:
        raise ErrorNegocio("El número de bolsas debe estar entre 1 y 30.")
    ancho = _ancho(conn)
    o = ordenes.obtener_orden(conn, orden_id)
    cli = o["cliente"]
    nombre = " ".join(filter(None, [cli["nombre"], cli["apellidos"]])) if cli else "MOSTRADOR"
    sep = "=" * ancho
    con_barras = codigo_barras_activo(conn)
    L: list[str] = []
    for n in range(1, bolsas + 1):
        L += [sep, *_centrado(o["folio"], ancho)]
        if con_barras:
            L.append(marca_codigo(o["folio"]))
        L += _centrado(nombre.upper()[:ancho], ancho)
        if cli and cli["telefono"]:
            L += _centrado(f"Tel. {cli['telefono']}", ancho)
        L += [*_centrado(f"BOLSA {n} DE {bolsas}", ancho), *_centrado(f"Entrega: {_fecha(o['fecha_promesa'])}", ancho)]
        if o.get("tipo_entrega") == "domicilio":
            L += _centrado("A DOMICILIO", ancho)
        if Decimal(o["saldo"]) > 0:
            L += _centrado(f"POR COBRAR ${_dinero(o['saldo'])}", ancho)
        L += [sep, "", ""]
    return "\n".join(L) + "\n"


# ---------- Código de barras del folio ----------------------------------------
# En el texto del ticket o de la etiqueta, una línea [[CODIGO:OC-000123]] marca dónde va el código de barras. La
# impresora térmica (ESC/POS) y el PDF la dibujan como barras Code128; en pantalla se ve como texto. Cualquier lector
# USB «tipo teclado» lo lee como si se escribiera el folio y Enter (en Órdenes encuentra la orden).

_MARCA = re.compile(r"^\[\[CODIGO:([\x21-\x5c\x5e-\x7e]{1,30})\]\]$")  # Code128 B: ASCII imprimible, sin «]»


def marca_codigo(folio: str) -> str:
    return f"[[CODIGO:{folio}]]"


def codigo_en_linea(linea: str) -> str | None:
    m = _MARCA.match(linea.strip())
    return m.group(1) if m else None


def codigo_barras_activo(conn) -> bool:
    return configuracion.obtener(conn, "codigo_barras", "si").strip().lower() in ("si", "sí", "1")


def para_pantalla(texto: str, ancho: int = 42) -> str:
    """El texto como se ve en la vista previa: la marca se muestra como un recuadro con el folio."""
    salida = []
    for linea in texto.split("\n"):
        codigo = codigo_en_linea(linea)
        salida.append(f"|||| {codigo} ||||".center(ancho).rstrip() if codigo else linea)
    return "\n".join(salida)


def codigo_barras_escpos(dato: str) -> bytes:
    """Code128 (juego B) centrado, de unos 10 mm de alto, con el folio legible debajo."""
    contenido = b"{B" + dato.encode("ascii")
    return (b"\x1ba\x01"          # centrar
            b"\x1dh\x50"          # alto: 80 puntos
            b"\x1dw\x02"          # ancho de cada barra: 2 puntos
            b"\x1dH\x02"          # folio legible debajo
            b"\x1dk\x49" + bytes([len(contenido)]) + contenido
            + b"\n\x1ba\x00")    # de vuelta a la izquierda


def _texto_escpos(texto: str) -> bytes:
    partes = []
    for linea in texto.rstrip("\n").split("\n"):
        codigo = codigo_en_linea(linea)
        partes.append(codigo_barras_escpos(codigo) if codigo else linea.encode("cp850", errors="replace") + b"\n")
    return b"".join(partes)


# ---------- Logo -------------------------------------------------------------

RUTA_LOGO = CARPETA_PROGRAMA / "oceanica" / "app" / "recursos" / "logo.png"


def logo_activo(conn) -> bool:
    return RUTA_LOGO.exists() and configuracion.obtener(conn, "ticket_logo", "si").strip().lower() in ("si", "sí", "1")


def _logo_en_grises(lado: int) -> tuple[int, int, list[float]]:
    """Logo escalado a `lado` puntos, sobre fondo blanco, en tonos de gris de 0 (negro) a 255 (blanco)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter

    origen = QImage(str(RUTA_LOGO))
    if origen.isNull():
        raise ErrorImpresion("No se pudo leer el logo del ticket.")
    origen = origen.scaled(lado, lado, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    fondo = QImage(origen.size(), QImage.Format_RGB32)
    fondo.fill(QColor("white"))
    p = QPainter(fondo)
    p.drawImage(0, 0, origen)
    p.end()
    gris = fondo.convertToFormat(QImage.Format_Grayscale8)
    w, h = gris.width(), gris.height()
    bpl = gris.bytesPerLine()
    datos = bytes(gris.constBits())
    return w, h, [float(datos[y * bpl + x]) for y in range(h) for x in range(w)]


def logo_escpos(ancho_caracteres: int) -> bytes:
    """Logo centrado como imagen de puntos ESC/POS (GS v 0), con difuminado Floyd-Steinberg."""
    puntos = 576 if ancho_caracteres >= 40 else 384     # papel de 80 mm o de 58 mm
    w, h, px = _logo_en_grises(int(puntos * 0.45))
    # más contraste: los fondos claros del logo quedan en blanco y no se llenan de puntitos
    px = [255.0 if v > 205 else max(0.0, v - 45) for v in px]
    for y in range(h):
        for x in range(w):
            i = y * w + x
            viejo = px[i]
            nuevo = 0.0 if viejo < 140 else 255.0
            px[i] = nuevo
            err = viejo - nuevo
            if x + 1 < w:
                px[i + 1] += err * 7 / 16
            if y + 1 < h:
                if x > 0:
                    px[i + w - 1] += err * 3 / 16
                px[i + w] += err * 5 / 16
                if x + 1 < w:
                    px[i + w + 1] += err * 1 / 16
    bytes_fila = (w + 7) // 8
    raster = bytearray()
    for y in range(h):
        for bx in range(bytes_fila):
            b = 0
            for bit in range(8):
                x = bx * 8 + bit
                if x < w and px[y * w + x] == 0:
                    b |= 0x80 >> bit
            raster.append(b)
    cabecera = b"\x1dv0\x00" + bytes([bytes_fila & 0xFF, bytes_fila >> 8, h & 0xFF, h >> 8])
    return b"\x1ba\x01" + cabecera + bytes(raster) + b"\n\x1ba\x00"


# ---------- PDF de ticket (vista previa o impresora no térmica) --------------

def texto_a_pdf_ticket(texto: str, ruta, logo: bool = False) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    lineas = texto.rstrip("\n").split("\n")
    alto_logo = 34 * mm if logo and RUTA_LOGO.exists() else 0
    alto_codigo = 17 * mm
    n_codigos = sum(1 for l in lineas if codigo_en_linea(l))
    alto = (len(lineas) - n_codigos) * 10 + n_codigos * alto_codigo + 24 + alto_logo
    c = canvas.Canvas(str(ruta), pagesize=(80 * mm, alto))
    y = alto - 14
    if alto_logo:
        lado = 30 * mm
        c.drawImage(str(RUTA_LOGO), (80 * mm - lado) / 2, alto - lado - 8, lado, lado, mask="auto")
        y -= alto_logo
    c.setFont("Courier", 8)
    for l in lineas:
        codigo = codigo_en_linea(l)
        if codigo:
            barras = code128.Code128(codigo, barHeight=11 * mm, barWidth=0.33 * mm, humanReadable=True, fontSize=8)
            barras.drawOn(c, (80 * mm - barras.width) / 2, y - 11 * mm)
            c.setFont("Courier", 8)
            y -= alto_codigo
            continue
        c.drawString(8, y, l)
        y -= 10
    c.save()
    return ruta


def ticket_orden_pdf(conn, orden_id: int, ruta) -> Path:
    return texto_a_pdf_ticket(ticket_orden_texto(conn, orden_id), ruta, logo_activo(conn))


# ---------- Impresión directa en Windows -------------------------------------

def listar_impresoras() -> list[str]:
    try:
        import win32print
    except ImportError:
        raise ErrorImpresion("La lista de impresoras requiere Windows y el paquete pywin32 (pip install pywin32).")
    return [p[2] for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)]


def imprimir_texto(texto: str, impresora: str | None = None, logo: bytes = b"") -> None:
    """Envía el ticket en modo RAW a una impresora térmica ESC/POS (código de página 850) y corta el papel."""
    try:
        import win32print
    except ImportError:
        log.warning("Impresión directa no disponible: falta pywin32 (o no es Windows)")
        raise ErrorImpresion("Esta computadora no puede imprimir directo en la impresora de tickets. "
                             "Puede abrir el PDF del ticket e imprimirlo desde ahí.")
    try:
        nombre = impresora or win32print.GetDefaultPrinter()
        datos = b"\x1b@" + logo + b"\x1bt\x02" + _texto_escpos(texto) + b"\n\n\n" + b"\x1dV\x42\x00"
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
        raise ErrorImpresion(f"No se pudo imprimir en «{impresora or 'la impresora predeterminada'}». Revise que esté "
                             "encendida, conectada y con papel. Si sigue igual, avise a la encargada.") from e


def imprimir_ticket_orden(conn, orden_id: int) -> None:
    logo = b""
    if logo_activo(conn):
        try:
            logo = logo_escpos(_ancho(conn))
        except ErrorImpresion:
            logo = b""  # sin logo antes que sin ticket
    imprimir_texto(ticket_orden_texto(conn, orden_id), configuracion.obtener(conn, "impresora_ticket", "") or None, logo)


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
