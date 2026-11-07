"""Validaciones estáticas del esquema (no requieren servidor MySQL)."""
import re

import pytest
import sqlglot

from oceanica.db import dividir_sentencias, listar_migraciones

MIGS = listar_migraciones()


def _todo_el_sql():
    return "\n".join(r.read_text(encoding="utf-8") for _, _, r in MIGS)


def test_migraciones_consecutivas():
    assert [v for v, _, _ in MIGS] == list(range(1, len(MIGS) + 1))


def test_todas_las_sentencias_son_mysql_valido():
    sentencias = dividir_sentencias(_todo_el_sql())
    assert len(sentencias) >= 40
    for s in sentencias:
        sqlglot.parse_one(s, read="mysql")  # lanza ParseError si no es válida


def test_hay_27_tablas_de_negocio():
    tablas = re.findall(r"CREATE TABLE (\w+)", _todo_el_sql())
    assert len(tablas) == 27
    assert len(set(tablas)) == 27


def test_todas_las_tablas_usan_innodb_y_utf8mb4():
    tablas = [s for s in dividir_sentencias(_todo_el_sql()) if s.startswith("CREATE TABLE")]
    assert len(tablas) == 27
    for bloque in tablas:
        assert "ENGINE=InnoDB" in bloque
        assert "utf8mb4" in bloque


def test_llaves_foraneas_apuntan_a_tablas_ya_creadas():
    sql = open(MIGS[0][2], encoding="utf-8").read()
    creadas = set()
    for bloque in re.findall(r"CREATE TABLE (\w+) \((.*?)\) ENGINE", sql, re.S):
        nombre, cuerpo = bloque
        for destino in re.findall(r"REFERENCES (\w+)", cuerpo):
            assert destino in creadas, f"{nombre} referencia {destino} antes de crearla"
        creadas.add(nombre)


def test_dinero_siempre_decimal():
    # Solo definiciones de columna (al inicio de línea), sin comentarios ni CHECK.
    sql = _todo_el_sql()
    for col in ("precio", "monto", "total", "subtotal", "neto", "existencia", "descuento"):
        for tipo in re.findall(rf"^\s+{col}\s+(\w+)", sql, re.M):
            assert tipo.upper() == "DECIMAL", (col, tipo)


def test_vistas_apuntan_a_tablas_existentes():
    tablas = set(re.findall(r"CREATE TABLE (\w+)", _todo_el_sql()))
    vistas = open(MIGS[1][2], encoding="utf-8").read()
    for t in re.findall(r"(?:FROM|JOIN) (\w+)", vistas):
        assert t in tablas, t


def test_no_hay_credenciales_fijas():
    for _, _, ruta in MIGS:
        assert "insert into usuarios" not in ruta.read_text(encoding="utf-8").lower()


def test_divisor_respeta_comillas_y_comentarios():
    s = dividir_sentencias("-- hola; mundo\nINSERT INTO t VALUES ('a;b'); SELECT 1;")
    assert s == ["INSERT INTO t VALUES ('a;b')", "SELECT 1"]


def test_collation_compatible_con_mariadb():
    assert "0900" not in _todo_el_sql()
