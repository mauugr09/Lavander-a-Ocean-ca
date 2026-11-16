"""Exportación de reportes a Excel (.xlsx) y PDF, con el diseño de la lavandería.

Cada archivo lleva: logo y nombre del negocio, título y periodo en palabras («Del 1 al 16 de noviembre
de 2026»), recuadros con lo más importante (totales, promedio y el mejor día o elemento), una gráfica
cuando el reporte tiene montos, una nota que explica las columnas y la tabla completa con su total.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import xlsxwriter
from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..config import CARPETA_PROGRAMA
from .comunes import ErrorNegocio

LOGO = CARPETA_PROGRAMA / "oceanica" / "app" / "recursos" / "logo.png"
AZUL, CIAN, VERDE, TEXTO, SUAVE, BORDE, FONDO = ("#0B3C9E", "#1AA6C8", "#1E8E5A", "#12263F", "#5B6F86",
                                                 "#D2E1EC", "#F2F8FC")
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]

# Explicación breve de cada reporte, para quien lo lee sin conocer el sistema.
NOTAS = {
    "Ventas por día": "«Vendido» es el total de las órdenes recibidas ese día. «Cobrado» es el dinero que entró ese "
                      "día, aunque sea de órdenes de días anteriores; por eso pueden no coincidir.",
    "Cobros por método de pago": "Dinero que entró en el periodo, separado por forma de pago. Los reembolsos se restan.",
    "Ventas por servicio": "Cuánto se vendió de cada servicio en las órdenes recibidas del periodo (sin canceladas).",
    "Órdenes pendientes": "Órdenes que aún no se entregan. «Días de retraso» cuenta desde la fecha prometida al cliente.",
    "Clientes frecuentes": "Clientes con más órdenes y lo que han gastado en total.",
    "Insumos con poca existencia": "Insumos que ya llegaron a su mínimo o están por debajo: conviene comprarlos.",
    "Asistencia": "Llegadas, salidas, retardos y horas trabajadas de cada empleado.",
    "Cortes de caja": "Cada cierre de caja con lo esperado, lo contado y la diferencia. Una diferencia distinta de "
                      "cero debe tener su explicación.",
    "Transferencias por confirmar": "Transferencias cobradas que todavía hay que verificar en el banco.",
}


# ---------- formato de valores -------------------------------------------------

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


def periodo_legible(subtitulo: str) -> str:
    """'Del 2026-11-01 al 2026-11-16' -> 'Del 1 al 16 de noviembre de 2026'."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})\D+(\d{4})-(\d{2})-(\d{2})", subtitulo or "")
    if not m:
        return subtitulo or ""
    a1, m1, d1, a2, m2, d2 = (int(x) for x in m.groups())
    if (a1, m1, d1) == (a2, m2, d2):
        return f"{d1} de {MESES[m1 - 1]} de {a1}"
    if a1 == a2 and m1 == m2:
        return f"Del {d1} al {d2} de {MESES[m1 - 1]} de {a1}"
    if a1 == a2:
        return f"Del {d1} de {MESES[m1 - 1]} al {d2} de {MESES[m2 - 1]} de {a1}"
    return f"Del {d1} de {MESES[m1 - 1]} de {a1} al {d2} de {MESES[m2 - 1]} de {a2}"


def _nota(reporte: dict) -> str:
    return next((n for t, n in NOTAS.items() if reporte["titulo"].startswith(t)), "")


def _columna_grafica(reporte: dict) -> tuple[str, str, str, str] | None:
    """(clave_etiqueta, tipo_etiqueta, clave_valor, encabezado_valor) si conviene graficar el reporte."""
    cols = reporte["columnas"]
    if not cols or cols[0][2] not in ("fecha", "texto") or not (2 <= len(reporte["filas"]) <= 62):
        return None
    valor = next((c for c in cols[1:] if c[2] == "dinero"), None) or next(
        (c for c in cols[1:] if c[2] == "numero" and c[0] != "id"), None)
    if not valor:
        return None
    return cols[0][0], cols[0][2], valor[0], valor[1]


def destacados(reporte: dict) -> list[tuple[str, str]]:
    """Hasta 4 recuadros de resumen: totales, promedio diario y el mejor día o elemento."""
    cols = {c[0]: c for c in reporte["columnas"]}
    tiles = [(cols[k][1], formatear(v, cols[k][2])) for k, v in reporte["totales"].items() if k in cols]
    g = _columna_grafica(reporte)
    filas = reporte["filas"]
    if g and filas:
        clave_et, tipo_et, clave_val, enc_val = g
        tipo_val = cols[clave_val][2]
        mejor = max(filas, key=lambda f: Decimal(f.get(clave_val) or 0))
        if Decimal(mejor.get(clave_val) or 0) > 0:
            tiles = tiles[:3]
            if tipo_et == "fecha":
                con_valor = [f for f in filas if Decimal(f.get(clave_val) or 0) > 0]
                prom = sum(Decimal(f.get(clave_val) or 0) for f in con_valor) / len(con_valor)
                if len(tiles) < 3:
                    tiles.append((f"Promedio por día ({enc_val.lower()})", formatear(prom, tipo_val)))
                tiles.append((f"Mejor día: {formatear(mejor[clave_et], 'fecha')}", formatear(mejor[clave_val], tipo_val)))
            else:
                nombre = str(mejor[clave_et])
                tiles.append((f"El más alto: {nombre if len(nombre) <= 28 else nombre[:27] + '…'}",
                              formatear(mejor[clave_val], tipo_val)))
    if not tiles:
        tiles.append(("Renglones", f"{len(filas):,}"))
    return tiles[:4]


def _float(v) -> float:
    return float(Decimal(v or 0))


# ---------- PDF ---------------------------------------------------------------------

class _CanvasNumerado(rl_canvas.Canvas):
    """Canvas que conoce el total de páginas para escribir «Página n de m» en el pie."""

    def __init__(self, *a, pie: str = "", **k):
        super().__init__(*a, **k)
        self._paginas, self._pie = [], pie

    def showPage(self):
        self._paginas.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._paginas)
        for estado in self._paginas:
            self.__dict__.update(estado)
            ancho, _ = self._pagesize
            self.setStrokeColor(colors.HexColor(BORDE))
            self.line(1.5 * cm, 1.3 * cm, ancho - 1.5 * cm, 1.3 * cm)
            self.setFont("Helvetica", 8)
            self.setFillColor(colors.HexColor(SUAVE))
            self.drawString(1.5 * cm, 0.9 * cm, self._pie)
            self.drawRightString(ancho - 1.5 * cm, 0.9 * cm, f"Página {self._pageNumber} de {total}")
            super().showPage()
        super().save()


def _estilos():
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=9, leading=12, textColor=colors.HexColor(TEXTO))
    return {
        "negocio": ParagraphStyle("negocio", base, fontName="Helvetica-Bold", fontSize=11, textColor=colors.HexColor(CIAN)),
        "titulo": ParagraphStyle("titulo", base, fontName="Helvetica-Bold", fontSize=20, leading=24,
                                 textColor=colors.HexColor(AZUL)),
        "periodo": ParagraphStyle("periodo", base, fontSize=11, leading=14, textColor=colors.HexColor(SUAVE)),
        "generado": ParagraphStyle("generado", base, fontSize=8, alignment=TA_RIGHT, textColor=colors.HexColor(SUAVE)),
        "seccion": ParagraphStyle("seccion", base, fontName="Helvetica-Bold", fontSize=12, leading=16,
                                  textColor=colors.HexColor(AZUL), spaceBefore=4, spaceAfter=4),
        "nota": ParagraphStyle("nota", base, fontSize=9, leading=12, textColor=colors.HexColor(SUAVE)),
        "tile_et": ParagraphStyle("tile_et", base, fontSize=8.5, textColor=colors.HexColor(SUAVE)),
        "tile_val": ParagraphStyle("tile_val", base, fontName="Helvetica-Bold", fontSize=14, leading=17,
                                   textColor=colors.HexColor(AZUL)),
        "celda": ParagraphStyle("celda", base, fontSize=8.5, leading=10.5),
        "enc": ParagraphStyle("enc", base, fontName="Helvetica-Bold", fontSize=8.5, leading=10.5, textColor=colors.white),
        "enc_der": ParagraphStyle("enc_der", base, fontName="Helvetica-Bold", fontSize=8.5, leading=10.5,
                                  textColor=colors.white, alignment=TA_RIGHT),
    }


def _encabezado_pdf(reporte, negocio, ancho, E):
    texto = [Paragraph(negocio or "&nbsp;", E["negocio"]), Paragraph(reporte["titulo"], E["titulo"])]
    periodo = periodo_legible(reporte["subtitulo"])
    if periodo:
        texto.append(Paragraph(periodo, E["periodo"]))
    generado = Paragraph(f"Generado el {datetime.now():%d/%m/%Y a las %H:%M}", E["generado"])
    logo = Image(str(LOGO), 2.1 * cm, 2.1 * cm) if LOGO.exists() else Spacer(2.1 * cm, 2.1 * cm)
    t = Table([[logo, texto, generado]], colWidths=[2.6 * cm, ancho - 2.6 * cm - 5 * cm, 5 * cm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("VALIGN", (2, 0), (2, 0), "BOTTOM"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                           ("LINEBELOW", (0, 0), (-1, 0), 2, colors.HexColor(AZUL))]))
    return t


def _tiles_pdf(reporte, ancho, E):
    tiles = destacados(reporte)
    celdas = [[Paragraph(et, E["tile_et"]), Paragraph(val, E["tile_val"])] for et, val in tiles]
    t = Table([celdas], colWidths=[ancho / len(tiles)] * len(tiles))
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(FONDO)),
                           ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(BORDE)),
                           ("LINEAFTER", (0, 0), (-2, -1), 0.6, colors.HexColor(BORDE)),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 8),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 9), ("LEFTPADDING", (0, 0), (-1, -1), 10)]))
    return t


def _formato_eje(v: float) -> str:
    return f"${v / 1000:,.0f} mil" if v >= 10000 else f"${v:,.0f}"


def _grafica_pdf(reporte, ancho) -> Drawing | None:
    g = _columna_grafica(reporte)
    if not g:
        return None
    clave_et, tipo_et, clave_val, enc_val = g
    filas = reporte["filas"]
    if tipo_et == "texto":
        filas = sorted(filas, key=lambda f: _float(f.get(clave_val)), reverse=True)[:10][::-1]
    valores = [_float(f.get(clave_val)) for f in filas]
    if not any(valores):
        return None
    es_dinero = next(c[2] for c in reporte["columnas"] if c[0] == clave_val) == "dinero"
    fmt = _formato_eje if es_dinero else (lambda v: f"{v:,.0f}")
    if tipo_et == "fecha":
        alto = 6.5 * cm
        d = Drawing(ancho, alto)
        ch = VerticalBarChart()
        ch.x, ch.y, ch.width, ch.height = 1.6 * cm, 1.0 * cm, ancho - 1.8 * cm, alto - 1.6 * cm
        paso = 1 if len(filas) <= 16 else 2 if len(filas) <= 32 else 4
        ch.categoryAxis.categoryNames = [f[clave_et].strftime("%d/%m") if i % paso == 0 else ""
                                         for i, f in enumerate(filas)]
        ch.categoryAxis.labels.fontSize = 7
        ch.categoryAxis.labels.angle = 0 if len(filas) <= 16 else 45
        ch.categoryAxis.labels.boxAnchor = "n" if len(filas) <= 16 else "ne"
    else:
        alto = max(4 * cm, len(filas) * 0.62 * cm + 1.8 * cm)
        d = Drawing(ancho, alto)
        ch = HorizontalBarChart()
        ch.x, ch.y, ch.width, ch.height = 5.2 * cm, 0.8 * cm, ancho - 6.6 * cm, alto - 1.7 * cm
        ch.categoryAxis.categoryNames = [str(f[clave_et])[:30] for f in filas]
        ch.categoryAxis.labels.fontSize = 8
        ch.categoryAxis.labels.boxAnchor = "e"
        ch.barLabelFormat = (lambda v: f"${v:,.0f}") if es_dinero else (lambda v: f"{v:,.0f}")
        ch.barLabels.fontSize = 7.5
        ch.barLabels.fontName = "Helvetica"
        ch.barLabels.boxAnchor = "w"
        ch.barLabels.dx = 3
    ch.data = [valores]
    ch.valueAxis.valueMin = 0
    ch.valueAxis.labels.fontSize = 7
    ch.valueAxis.labels.fontName = ch.categoryAxis.labels.fontName = "Helvetica"
    ch.valueAxis.labels.fillColor = ch.categoryAxis.labels.fillColor = colors.HexColor(SUAVE)
    ch.valueAxis.labelTextFormat = fmt
    ch.valueAxis.strokeColor = colors.HexColor(BORDE)
    ch.valueAxis.gridStrokeColor = colors.HexColor("#E3ECF4")
    ch.valueAxis.visibleGrid = True
    ch.categoryAxis.strokeColor = colors.HexColor(BORDE)
    ch.bars.strokeColor = None
    ch.bars[0].fillColor = colors.HexColor(AZUL if tipo_et == "fecha" else CIAN)
    mejor = valores.index(max(valores))
    ch.bars[(0, mejor)].fillColor = colors.HexColor(VERDE)
    ch.barSpacing = 1
    d.add(ch)
    d.add(String(0, alto - 0.35 * cm, f"{enc_val} ({'por día' if tipo_et == 'fecha' else 'los 10 más altos'}). "
                                      "En verde, el más alto.", fontName="Helvetica", fontSize=8,
                 fillColor=colors.HexColor(SUAVE)))
    return d


def _tabla_pdf(reporte, ancho, E):
    cols = reporte["columnas"]
    pesos = [3.0 if c[2] == "texto" else 2.0 if c[2] == "fechahora" else 1.6 for c in cols]
    anchos = [ancho * p / sum(pesos) for p in pesos]
    datos = [[Paragraph(c[1], E["enc_der"] if c[2] in ("dinero", "numero") else E["enc"]) for c in cols]]
    tenues = []
    for i, fila in enumerate(reporte["filas"], start=1):
        renglon = []
        for j, (clave, _, tipo) in enumerate(cols):
            v = fila.get(clave)
            texto = formatear(v, tipo)
            if tipo in ("dinero", "numero") and v is not None and Decimal(v) == 0:
                tenues.append((j, i))
            renglon.append(Paragraph(texto, E["celda"]) if tipo == "texto" else texto)
        datos.append(renglon)
    totales = _fila_totales(reporte)
    if totales:
        datos.append(totales)
    estilo = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(AZUL)),
              ("FONTNAME", (0, 1), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 1), (-1, -1), 8.5),
              ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor(TEXTO)),
              ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F8FC")]),
              ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#E3ECF4")),
              ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(BORDE)),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 5),
              ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 6),
              ("RIGHTPADDING", (0, 0), (-1, -1), 6)]
    for j, (_, _, tipo) in enumerate(cols):
        if tipo in ("dinero", "numero"):
            estilo.append(("ALIGN", (j, 1), (j, -1), "RIGHT"))
    for j, i in tenues:
        estilo.append(("TEXTCOLOR", (j, i), (j, i), colors.HexColor("#A9B6C4")))
    if totales:
        estilo += [("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E6F0FF")),
                   ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, -1), (-1, -1), 9),
                   ("TEXTCOLOR", (0, -1), (-1, -1), colors.HexColor(AZUL)),
                   ("LINEABOVE", (0, -1), (-1, -1), 1.2, colors.HexColor(AZUL))]
    t = Table(datos, colWidths=anchos, repeatRows=1)
    t.setStyle(TableStyle(estilo))
    return t


def exportar_pdf(reporte: dict, ruta, negocio: str = "") -> Path:
    if not reporte["filas"] and not reporte["totales"]:
        raise ErrorNegocio("No hay datos para exportar en este reporte.")
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    pagina = landscape(LETTER) if len(reporte["columnas"]) > 5 else LETTER
    doc = SimpleDocTemplate(str(ruta), pagesize=pagina, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.3 * cm, bottomMargin=1.8 * cm, title=reporte["titulo"],
                            author=negocio or "Oceánica Gestión")
    ancho = pagina[0] - 3 * cm
    E = _estilos()
    elementos = [_encabezado_pdf(reporte, negocio, ancho, E), Spacer(1, 0.45 * cm),
                 _tiles_pdf(reporte, ancho, E), Spacer(1, 0.35 * cm)]
    nota = _nota(reporte)
    if nota:
        elementos += [Paragraph(f"<b>Cómo leer este reporte:</b> {nota}", E["nota"]), Spacer(1, 0.3 * cm)]
    grafica = _grafica_pdf(reporte, ancho)
    if grafica is not None:
        elementos += [KeepTogether([Paragraph("Gráfica", E["seccion"]), grafica]), Spacer(1, 0.3 * cm)]
    if reporte["filas"]:
        elementos += [Paragraph(f"Detalle ({len(reporte['filas']):,} renglones)", E["seccion"]),
                      _tabla_pdf(reporte, ancho, E)]
    else:
        elementos.append(Paragraph("No hay datos en este periodo.", E["seccion"]))
    pie = f"{negocio} · {reporte['titulo']}" if negocio else reporte["titulo"]
    doc.build(elementos, canvasmaker=lambda *a, **k: _CanvasNumerado(*a, pie=pie, **k))
    return ruta


# ---------- Excel -------------------------------------------------------------------

def exportar_xlsx(reporte: dict, ruta, negocio: str = "") -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    cols = reporte["columnas"]
    n = len(cols)
    wb = xlsxwriter.Workbook(str(ruta))
    wb.set_properties({"title": reporte["titulo"], "author": negocio or "Oceánica Gestión"})
    ws = wb.add_worksheet(re.sub(r"[\[\]:*?/\\]", "-", reporte["titulo"])[:31])
    ws.hide_gridlines(2)
    ws.set_zoom(110)

    F = lambda **k: wb.add_format({"font_name": "Calibri", "font_color": TEXTO, "valign": "vcenter", **k})  # noqa: E731
    f_negocio = F(bold=True, font_size=11, font_color=CIAN)
    f_titulo = F(bold=True, font_size=20, font_color=AZUL)
    f_periodo = F(font_size=11, font_color=SUAVE)
    f_tile_et = F(font_size=9, font_color=SUAVE, bg_color=FONDO, top=1, left=1, right=1, border_color=BORDE)
    f_tile_val = F(bold=True, font_size=14, font_color=AZUL, bg_color=FONDO, bottom=1, left=1, right=1,
                   border_color=BORDE, align="left")
    f_nota = F(font_size=9, font_color=SUAVE, text_wrap=True, valign="top")
    f_seccion = F(bold=True, font_size=12, font_color=AZUL)
    f_enc = F(bold=True, font_color="#FFFFFF", bg_color=AZUL)
    formatos = {
        "texto": F(text_wrap=False), "dinero": F(num_format="$#,##0.00"), "numero": F(num_format="#,##0.##"),
        "fecha": F(num_format="dd/mm/yyyy", align="left"), "fechahora": F(num_format="dd/mm/yyyy hh:mm", align="left"),
    }

    # encabezado con logo
    ws.set_row(0, 22)
    ws.set_row(1, 30)
    if LOGO.exists():
        ws.insert_image(0, 0, str(LOGO), {"x_scale": 0.15, "y_scale": 0.15, "x_offset": 4, "y_offset": 4,
                                          "object_position": 3})
    inicio = 1 if LOGO.exists() else 0
    ws.write(0, inicio, negocio or "", f_negocio)
    ws.write(1, inicio, reporte["titulo"], f_titulo)
    ws.write(2, inicio, periodo_legible(reporte["subtitulo"]), f_periodo)
    ws.write(3, inicio, f"Generado el {datetime.now():%d/%m/%Y a las %H:%M}", F(font_size=8, font_color=SUAVE))

    # recuadros de resumen (cada uno ocupa 2 columnas)
    fila = 5
    for i, (et, val) in enumerate(destacados(reporte)):
        c = inicio + i * 2
        ws.merge_range(fila, c, fila, c + 1, et, f_tile_et)
        ws.merge_range(fila + 1, c, fila + 1, c + 1, val, f_tile_val)
    ws.set_row(fila + 1, 24)
    fila += 3
    nota = _nota(reporte)
    if nota:
        ws.merge_range(fila, 0, fila, max(n - 1, inicio + 7), f"Cómo leer este reporte: {nota}", f_nota)
        ws.set_row(fila, 32)
        fila += 2

    if not reporte["filas"]:
        ws.write(fila, 0, "No hay datos en este periodo.", f_seccion)
        wb.close()
        return ruta

    # tabla con filtros, colores alternos y fila de total
    ws.write(fila, 0, f"Detalle ({len(reporte['filas']):,} renglones)", f_seccion)
    fila += 1
    primera, ultima = fila, fila + len(reporte["filas"])
    datos = []
    for r in reporte["filas"]:
        renglon = []
        for clave, _, tipo in cols:
            v = r.get(clave)
            if v is None:
                renglon.append(None)
            elif tipo in ("dinero", "numero"):
                renglon.append(float(v))
            elif tipo in ("fecha", "fechahora") and isinstance(v, (date, datetime)):
                renglon.append(v if isinstance(v, datetime) else datetime.combine(v, datetime.min.time()))
            else:
                renglon.append(str(v))
        datos.append(renglon)
    columnas = []
    for j, (clave, enc, tipo) in enumerate(cols):
        col = {"header": enc, "format": formatos[tipo], "header_format": f_enc}
        if clave in reporte["totales"]:
            col.update({"total_function": "sum", "total_value": float(reporte["totales"][clave])})
        elif j == 0 and reporte["totales"]:
            col["total_string"] = "TOTAL"
        columnas.append(col)
    ws.add_table(primera, 0, ultima + (1 if reporte["totales"] else 0), n - 1,
                 {"data": datos, "columns": columnas, "style": "Table Style Medium 2",
                  "total_row": bool(reporte["totales"]), "name": "Reporte"})
    ws.freeze_panes(primera + 1, 0)
    for j, (clave, enc, tipo) in enumerate(cols):
        largo = max([len(enc)] + [len(formatear(r.get(clave), tipo)) for r in reporte["filas"][:500]])
        ws.set_column(j, j, min(max(largo + 3, 12), 45))

    # gráfica a la derecha de la tabla
    g = _columna_grafica(reporte)
    if g:
        clave_et, tipo_et, clave_val, enc_val = g
        j_et = next(i for i, c in enumerate(cols) if c[0] == clave_et)
        j_val = next(i for i, c in enumerate(cols) if c[0] == clave_val)
        hoja = ws.get_name()
        graf = wb.add_chart({"type": "column" if tipo_et == "fecha" else "bar"})
        graf.add_series({"name": enc_val,
                         "categories": [hoja, primera + 1, j_et, ultima, j_et],
                         "values": [hoja, primera + 1, j_val, ultima, j_val],
                         "fill": {"color": AZUL if tipo_et == "fecha" else CIAN}, "gap": 60})
        graf.set_title({"name": f"{enc_val} {'por día' if tipo_et == 'fecha' else 'por elemento'}",
                        "name_font": {"size": 12, "color": AZUL, "bold": True}})
        graf.set_legend({"none": True})
        graf.set_y_axis({"num_format": "$#,##0" if cols[j_val][2] == "dinero" else "#,##0",
                         "major_gridlines": {"visible": True, "line": {"color": "#E3ECF4"}}})
        if tipo_et == "fecha":
            graf.set_x_axis({"date_axis": True, "num_format": "dd/mm", "major_unit": 1 if len(reporte["filas"]) <= 16 else 2,
                             "major_unit_type": "days", "num_font": {"rotation": -45 if len(reporte["filas"]) > 16 else 0}})
        if tipo_et == "texto":
            graf.set_y_axis({"reverse": True})
            graf.set_x_axis({"num_format": "$#,##0" if cols[j_val][2] == "dinero" else "#,##0"})
        graf.set_chartarea({"border": {"color": BORDE}})
        graf.set_size({"width": 620, "height": 340 if tipo_et == "fecha" else max(300, 26 * len(reporte["filas"]))})
        ws.insert_chart(primera, n + 1, graf, {"x_offset": 10, "y_offset": 0})

    # impresión
    if n > 5 or g:
        ws.set_landscape()
    ws.set_paper(1)
    ws.fit_to_pages(1, 0)
    ws.repeat_rows(primera)
    ws.set_footer(f"&L&8{negocio}&C&8{reporte['titulo']}&R&8Página &P de &N")
    wb.close()
    return ruta


def exportar(reporte: dict, ruta, negocio: str = "") -> Path:
    """Elige el formato por la extensión: .xlsx o .pdf."""
    sufijo = Path(ruta).suffix.lower()
    if sufijo == ".xlsx":
        return exportar_xlsx(reporte, ruta, negocio)
    if sufijo == ".pdf":
        return exportar_pdf(reporte, ruta, negocio)
    raise ErrorNegocio("Formato no soportado: use .xlsx o .pdf")
