"""Paleta tomada del logo de la lavandería y hoja de estilos de la aplicación."""

PRIMARIO = "#0B3C9E"     # azul profundo del colibrí
PRIMARIO_OSCURO = "#082B73"
SECUNDARIO = "#1AA6C8"   # cian de las letras
ACENTO = "#7B3FA0"       # morado del pecho del colibrí (solo detalles)
FONDO = "#F2F8FC"
TEXTO = "#12263F"
TEXTO_SUAVE = "#5B6F86"
BORDE = "#D2E1EC"
OK = "#1E8E5A"
ALERTA = "#B86E00"
ERROR = "#C0392B"

HOJA_ESTILO = f"""
* {{ font-size: 10.5pt; color: {TEXTO}; }}
QMainWindow, QDialog, QWidget#pagina, QWidget#fondo {{ background: {FONDO}; }}
QLabel[rol="titulo"] {{ font-size: 17pt; font-weight: 700; color: {PRIMARIO}; }}
QLabel[rol="subtitulo"] {{ font-size: 11pt; font-weight: 600; color: {PRIMARIO}; }}
QLabel[rol="suave"] {{ color: {TEXTO_SUAVE}; }}
QLabel[rol="total"] {{ font-size: 24pt; font-weight: 700; color: {PRIMARIO}; }}
QLabel[rol="error"] {{ color: {ERROR}; font-weight: 600; }}
QLabel[rol="chip_ok"] {{ background: #DDF3E8; color: {OK}; border-radius: 10px; padding: 3px 12px; font-weight: 600; }}
QLabel[rol="chip_alerta"] {{ background: #FCEBD0; color: {ALERTA}; border-radius: 10px; padding: 3px 12px; font-weight: 600; }}
QLabel[rol="chip_neutro"] {{ background: #E3ECF4; color: {TEXTO_SUAVE}; border-radius: 10px; padding: 3px 12px; font-weight: 600; }}
QFrame[rol="tarjeta"] {{ background: white; border: 1px solid {BORDE}; border-radius: 10px; }}
QPushButton {{ background: white; border: 1px solid {BORDE}; border-radius: 6px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {SECUNDARIO}; }}
QPushButton:pressed {{ background: #E6F3FA; }}
QPushButton:disabled {{ color: #9FB0C0; background: #EEF3F7; }}
QPushButton[rol="primario"] {{ background: {PRIMARIO}; color: white; border: none; font-weight: 600; }}
QPushButton[rol="primario"]:hover {{ background: {PRIMARIO_OSCURO}; }}
QPushButton[rol="primario"]:disabled {{ background: #9DB3D9; color: white; }}
QPushButton[rol="peligro"] {{ color: {ERROR}; border-color: #E3B5AF; }}
QLineEdit, QComboBox, QDateTimeEdit, QDateEdit, QDoubleSpinBox, QSpinBox, QPlainTextEdit {{
  background: white; border: 1px solid {BORDE}; border-radius: 6px; padding: 6px 8px; }}
QLineEdit:focus, QComboBox:focus, QDateTimeEdit:focus, QDateEdit:focus, QPlainTextEdit:focus {{ border: 2px solid {SECUNDARIO}; padding: 5px 7px; }}
QTableWidget {{ background: white; alternate-background-color: #F6FAFD; border: 1px solid {BORDE};
  gridline-color: #E8F0F6; selection-background-color: #CFEAF7; selection-color: {TEXTO}; }}
QTableWidget:focus {{ border: 2px solid {SECUNDARIO}; }}
QHeaderView::section {{ background: #E8F1F8; border: none; border-bottom: 1px solid {BORDE}; padding: 7px; font-weight: 600; }}
QListWidget#nav {{ background: {PRIMARIO}; border: none; outline: 0; padding-top: 6px; }}
QListWidget#nav::item {{ color: white; padding: 12px 16px; border-radius: 6px; margin: 2px 8px; }}
QListWidget#nav::item:hover {{ background: #1B50B3; }}
QListWidget#nav::item:selected {{ background: {SECUNDARIO}; color: white; font-weight: 600; }}
QFrame#barra {{ background: white; border-bottom: 1px solid {BORDE}; }}
QTabWidget::pane {{ border: 1px solid {BORDE}; background: white; border-radius: 6px; }}
QTabBar::tab {{ padding: 8px 16px; background: #E8F1F8; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: white; font-weight: 600; color: {PRIMARIO}; }}
QToolTip {{ background: white; color: {TEXTO}; border: 1px solid {BORDE}; }}
"""
