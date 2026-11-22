"""Respaldo diario en el Programador de tareas de Windows. Aquí se revisa la definición de la tarea y la hora;
la creación real con schtasks la prueba el CI en Windows (paso «El respaldo diario queda programado»)."""
import sys
import xml.etree.ElementTree as ET
from datetime import date

import pytest

from oceanica import programar_respaldo as pr

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def _tarea(programa=r"C:\Program Files\Oceanica & Cía\OceanicaAdmin.exe", hora="21:00"):
    return ET.fromstring(pr.xml_tarea(programa, "respaldo --auto", hora, date(2026, 11, 22)).split("?>", 1)[1])


def test_la_tarea_se_recupera_si_la_pc_estaba_apagada_y_no_guarda_contrasena():
    t = _tarea()
    assert t.find("t:Settings/t:StartWhenAvailable", NS).text == "true"      # la lavandería cierra antes de las 21:00
    assert t.find("t:Settings/t:DisallowStartIfOnBatteries", NS).text == "false"   # laptop con cargador o sin él
    assert t.find("t:Principals/t:Principal/t:LogonType", NS).text == "InteractiveToken"   # sin contraseña guardada
    assert t.find("t:Triggers/t:CalendarTrigger/t:StartBoundary", NS).text == "2026-11-22T21:00:00"
    assert t.find("t:Triggers/t:CalendarTrigger/t:ScheduleByDay/t:DaysInterval", NS).text == "1"
    exe = t.find("t:Actions/t:Exec", NS)
    assert exe.find("t:Command", NS).text == r"C:\Program Files\Oceanica & Cía\OceanicaAdmin.exe"   # «&» escapado
    assert exe.find("t:Arguments", NS).text == "respaldo --auto"


@pytest.mark.parametrize("mala", ["9:00", "24:00", "21:60", "21", "", "21:00; del"])
def test_hora_invalida_se_rechaza(mala):
    with pytest.raises(ValueError):
        pr.xml_tarea("x.exe", "respaldo --auto", mala)


def test_empaquetado_llama_a_la_version_con_consola(tmp_path, monkeypatch):
    (tmp_path / "Oceanica.exe").write_text("")
    (tmp_path / "OceanicaAdmin.exe").write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Oceanica.exe"))
    assert pr.comando_respaldo() == (str(tmp_path / "OceanicaAdmin.exe"), "respaldo --auto")


def test_sin_empaquetar_usa_python():
    assert pr.comando_respaldo() == (sys.executable, "-m oceanica.respaldos --auto")


def test_la_hora_sale_de_la_configuracion(conn, monkeypatch):
    from .conftest import _CFG
    monkeypatch.setattr("oceanica.config.cargar_config", lambda *a, **k: _CFG)
    cur = conn.cursor()
    for valor, esperado in (("19:30", "19:30"), ("mañana", pr.HORA_POR_OMISION)):
        cur.execute("UPDATE configuracion SET valor = %s WHERE clave = 'respaldo_hora'", (valor,))
        conn.commit()
        assert pr.hora_configurada() == esperado
    cur.close()


def test_sin_base_usa_la_hora_por_omision(monkeypatch):
    def sin_base(*a, **k):
        raise FileNotFoundError("sin config")
    monkeypatch.setattr("oceanica.config.cargar_config", sin_base)
    assert pr.hora_configurada() == pr.HORA_POR_OMISION


@pytest.mark.skipif(sys.platform == "win32", reason="en Windows lo prueba el CI con schtasks real")
def test_fuera_de_windows_avisa_y_no_hace_nada(capsys):
    assert pr.main([]) == 1 and "solo se configura en Windows" in capsys.readouterr().out
