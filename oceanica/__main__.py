"""Punto de entrada.

    Oceanica.exe              abre el programa
    Oceanica.exe migrar       aplica las migraciones pendientes
    Oceanica.exe configurar   conecta a una base ya creada (sin root)
    Oceanica.exe instalar     crea la base, el usuario y el administrador (pide root una vez)
    Oceanica.exe respaldo     respaldo de la base (para el Programador de tareas): respaldo --auto
    Oceanica.exe programar-respaldo  crea el respaldo diario en el Programador de tareas (--quitar lo elimina)
    Oceanica.exe restablecer-admin   contraseña temporal para un administrador que no puede entrar (pide root)
"""
import sys

COMANDOS = {"migrar": "migrar", "configurar": "configurar", "instalar": "init_db", "respaldo": "respaldos",
            "restablecer-admin": "restablecer_admin", "programar-respaldo": "programar_respaldo"}


def _ejecutar() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in COMANDOS:
        import importlib
        modulo = importlib.import_module(f"oceanica.{COMANDOS[sys.argv[1]]}")
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        return modulo.main() or 0
    # La pantalla de carga sale antes de importar el resto del programa (que es lo que más tarda en abrir)
    from oceanica.app.carga import iniciar_pantalla_carga
    pantalla = iniciar_pantalla_carga()
    from oceanica.app.aplicacion import main
    return main(pantalla)


if __name__ == "__main__":
    sys.exit(_ejecutar())
