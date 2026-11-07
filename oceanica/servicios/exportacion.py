"""Exportación de reportes a Excel (.xlsx) y PDF."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import xlsxwriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .comunes import ErrorNegocio


def formatear(valor, tipo: str) -> str:
    """Texto legible de un valor según el tipo de columna (para PDF y pantalla)."""
    if valor is None:
        return ""
    if tipo == "dinero":
        return f"${Decimal(valor):,.2f}"
    if tipo == "numero":
        n = Decimal(valor)
        return f"{n:,.0f}" if n == n.to_integral_value() else f"{n:,.2f}"
    if tipo == "fecha":
        return valor.strftime("%d/%m/%Y") if isinstance(valor, (date, datetime)) else str(valor)
    if tipo == "fechahora":
        return valor.strftime("%d/%m/%Y %H:%M") if isinstance(valor, datetime) else (
            valor.strftime("%d/%m/%Y") if isinstance(valor, date) else str(valor))
    return str(valor)


def _fila_totales(reporte: dict) -> list[str] | None:
    if not reporte["totales"]:
        return None
    fila = []
    for i, (clave, _, tipo) in enumerate(reporte["columnas"]):
        if clave in reporte["totales"]:
            fila.append(formatear(reporte["totales"][clave], tipo))
        else:
            fila.append("TOTAL" if i == 0 else "")
    return fila


def exportar_xlsx(reporte: dict, ruta, negocio: str = "") -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    wb = xlsxwriter.Workbook(str(ruta))
    ws = wb.add_worksheet(reporte["titulo"][:31].replace("/", "-"))
    f_titulo = wb.add_format({"bold": True, "font_size": 14})
    f_sub = wb.add_format({"italic": True, "font_color": "#555555"})
    f_enc = wb.add_format({"bold": True, "bg_color": "#1F4E79", "font_color": "#FFFFFF", "border": 1})
    f = {
        "texto": wb.add_format({"border": 1}),
        "dinero": wb.add_format({"border": 1, "num_format": "$#,##0.00"}),
        "numero": wb.add_format({"border": 1, "num_format": "#,##0.##"}),
        "fecha": wb.add_format({"border": 1, "num_format": "dd/mm/yyyy"}),
        "fechahora": wb.add_format({"border": 1, "num_format": "dd/mm/yyyy hh:mm"}),
    }
    f_tot = wb.add_format({"bold": True, "top": 2, "num_format": "$#,##0.00"})
    f_tot_txt = wb.add_format({"bold": True, "top": 2})
    ws.write(0, 0, f"{negocio} - {reporte['titulo']}" if negocio else reporte["titulo"], f_titulo)
    ws.write(1, 0, reporte["subtitulo"], f_sub)
    fila0 = 3
    anchos = [len(c[1]) for c in reporte["columnas"]]
    for j, (_, enc, _) in enumerate(reporte["columnas"]):
        ws.write(fila0, j, enc, f_enc)
    for i, fila in enumerate(reporte["filas"], start=fila0 + 1):
        for j, (clave, _, tipo) in enumerate(reporte["columnas"]):
            v = fila.get(clave)
            anchos[j] = max(anchos[j], len(formatear(v, tipo)))
            if v is None:
                ws.write_blank(i, j, None, f[tipo])
            elif tipo in ("dinero", "numero"):
                ws.write_number(i, j, float(v), f[tipo])
            elif tipo in ("fecha", "fechahora") and isinstance(v, (date, datetime)):
                ws.write_datetime(i, j, v if isinstance(v, datetime) else datetime.combine(v, datetime.min.time()), f[tipo])
            else:
                ws.write(i, j, str(v), f["texto"])
    totales = _fila_totales(reporte)
    if totales:
        fila_t = fila0 + 1 + len(reporte["filas"])
        for j, (clave, _, tipo) in enumerate(reporte["columnas"]):
            if clave in reporte["totales"]:
                ws.write_number(fila_t, j, float(reporte["totales"][clave]), f_tot if tipo == "dinero" else f_tot_txt)
            else:
                ws.write(fila_t, j, "TOTAL" if j == 0 else "", f_tot_txt)
    for j, a in enumerate(anchos):
        ws.set_column(j, j, min(max(a + 2, 10), 45))
    ws.freeze_panes(fila0 + 1, 0)
    wb.close()
    return ruta


def exportar_pdf(reporte: dict, ruta, negocio: str = "") -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    cols = reporte["columnas"]
    pagina = landscape(LETTER) if len(cols) > 5 else LETTER
    doc = SimpleDocTemplate(str(ruta), pagesize=pagina, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm, title=reporte["titulo"])
    est = getSampleStyleSheet()
    elementos = [Paragraph(negocio or "&nbsp;", est["Title"]), Paragraph(reporte["titulo"], est["Heading2"])]
    if reporte["subtitulo"]:
        elementos.append(Paragraph(reporte["subtitulo"], est["Italic"]))
    elementos.append(Spacer(1, 0.4 * cm))
    datos = [[c[1] for c in cols]]
    for fila in reporte["filas"]:
        datos.append([formatear(fila.get(c[0]), c[2]) for c in cols])
    totales = _fila_totales(reporte)
    if totales:
        datos.append(totales)
    if len(datos) == 1:
        raise ErrorNegocio("No hay datos para exportar en este reporte.")
    estilo = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
              ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
              ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
              ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6FA")]),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
    for j, (_, _, tipo) in enumerate(cols):
        if tipo in ("dinero", "numero"):
            estilo.append(("ALIGN", (j, 1), (j, -1), "RIGHT"))
    if totales:
        estilo += [("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black)]
    tabla = Table(datos, repeatRows=1)
    tabla.setStyle(TableStyle(estilo))
    elementos.append(tabla)
    elementos += [Spacer(1, 0.5 * cm), Paragraph(f"Generado el {datetime.now():%d/%m/%Y %H:%M}", est["Normal"])]
    doc.build(elementos)
    return ruta


def exportar(reporte: dict, ruta, negocio: str = "") -> Path:
    """Elige el formato por la extensión: .xlsx o .pdf."""
    sufijo = Path(ruta).suffix.lower()
    if sufijo == ".xlsx":
        return exportar_xlsx(reporte, ruta, negocio)
    if sufijo == ".pdf":
        return exportar_pdf(reporte, ruta, negocio)
    raise ErrorNegocio("Formato no soportado: usa .xlsx o .pdf")
