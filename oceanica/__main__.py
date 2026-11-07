"""Punto de entrada.

    Oceanica.exe              abre el programa
    Oceanica.exe migrar       aplica las migraciones pendientes
    Oceanica.exe configurar   conecta a una base ya creada (sin root)
    Oceanica.exe instalar     crea la base, el usuario y el administrador (pide root una vez)
    Oceanica.exe respaldo     respaldo de la base (para el Programador de tareas): respaldo --auto
"""
import sys

COMANDOS = {"migrar": "migrar", "configurar": "configurar", "instalar": "init_db", "respaldo": "respaldos"}


def _ejecutar() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in COMANDOS:
        import importlib
        modulo = importlib.import_module(f"oceanica.{COMANDOS[sys.argv[1]]}")
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        return modulo.main() or 0
    from oceanica.app.aplicacion import main
    return main()


if __name__ == "__main__":
    sys.exit(_ejecutar())
