from datetime import datetime, timedelta

from oceanica import seguridad as s


def test_politica_rechaza_cortas_y_numericas():
    assert s.validar_politica("abc")
    assert s.validar_politica("12345678")
    assert s.validar_politica("Lavanderia2026") == []


def test_hash_y_verificacion():
    h = s.hashear("Secreta#2026")
    assert h != "Secreta#2026"
    assert s.verificar("Secreta#2026", h)
    assert not s.verificar("otra", h)
    assert not s.verificar("x", "no-es-un-hash")


def test_hashes_distintos_para_misma_clave():
    assert s.hashear("Misma#Clave1") != s.hashear("Misma#Clave1")


def test_bloqueo_temporal():
    ahora = datetime(2026, 11, 4, 12, 0)
    assert s.esta_bloqueado(ahora + timedelta(minutes=5), ahora)
    assert not s.esta_bloqueado(ahora - timedelta(minutes=1), ahora)
    assert not s.esta_bloqueado(None, ahora)


def test_requiere_rol():
    s.requiere_rol({"rol": "administrador"}, "administrador")
    try:
        s.requiere_rol({"rol": "empleado"}, "administrador")
    except s.ErrorAcceso:
        return
    raise AssertionError("debió negar el acceso")


class _CursorFalso:
    """Simula la base para probar el flujo de bloqueo sin MySQL."""
    def __init__(self, fila):
        self.fila, self.updates = fila, []
    def execute(self, sql, params=None):
        self.ultimo = sql
        if sql.startswith("UPDATE usuarios SET intentos_fallidos = %s"):
            self.updates.append(params)
    def fetchone(self):
        return self.fila if self.ultimo.startswith("SELECT u.id") else None
    def close(self): pass


class _ConnFalsa:
    def __init__(self, fila): self.cur = _CursorFalso(fila)
    def cursor(self, **k): return self.cur
    def commit(self): pass
    def rollback(self): pass


def _fila(intentos):
    return {"id": 1, "usuario": "admin", "password_hash": s.hashear("Correcta#123"),
            "activo": 1, "intentos_fallidos": intentos, "bloqueado_hasta": None,
            "debe_cambiar_password": 0, "empleado_id": None, "rol": "administrador"}


def test_quinto_intento_fallido_bloquea():
    conn = _ConnFalsa(_fila(4))
    try:
        s.iniciar_sesion(conn, "admin", "mala")
    except s.ErrorAcceso:
        pass
    intentos, bloqueo, _id = conn.cur.updates[0]
    assert intentos == 0 and bloqueo is not None


def test_login_correcto_devuelve_rol():
    conn = _ConnFalsa(_fila(2))
    sesion = s.iniciar_sesion(conn, "admin", "Correcta#123")
    assert sesion["rol"] == "administrador"


def test_usuario_inexistente_mismo_mensaje():
    conn = _ConnFalsa(None)
    try:
        s.iniciar_sesion(conn, "nadie", "x")
    except s.ErrorAcceso as e:
        assert "incorrectos" in str(e)
